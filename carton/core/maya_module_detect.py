"""Detection and parsing for Autodesk Maya module folders.

A Maya module folder is recognized by either:

- ``PackageContents.xml`` at the folder root (Autodesk Application Package
  format), or
- a ``*.mod`` file at the folder root (classic Maya module).

The parsers here are intentionally lenient: real-world ``.mod`` files and
PackageContents.xml documents in the wild use a wide variety of conventions,
and Carton only needs the bits required to wire up env vars and run
``userSetup.py``. Anything we can't extract falls back to the standard
``Contents/scripts``, ``Contents/plug-ins``, ``Contents/icons`` layout.
"""

import os
import re
import xml.etree.ElementTree as ET


def find_module_files(folder):
    """Return ``(package_contents_path_or_None, [mod_file_paths])``.

    Looks only at the folder root; doesn't recurse.
    """
    pkg_contents = None
    mod_files = []
    if not folder or not os.path.isdir(folder):
        return (None, [])
    for entry in os.listdir(folder):
        full = os.path.join(folder, entry)
        if not os.path.isfile(full):
            continue
        if entry == "PackageContents.xml":
            pkg_contents = full
        elif entry.lower().endswith(".mod"):
            mod_files.append(full)
    return (pkg_contents, mod_files)


def is_maya_module(folder):
    """True if ``folder`` looks like a Maya module."""
    pkg_contents, mod_files = find_module_files(folder)
    return bool(pkg_contents or mod_files)


def parse_package_contents(path):
    """Parse a ``PackageContents.xml`` file.

    Returns a dict with ``name`` (str) and ``user_setup`` (relative path or
    None). Missing fields just don't appear in the dict. Returns ``{}`` on
    parse error.
    """
    out = {}
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return out
    root = tree.getroot()

    name = root.get("Name") or root.get("name")
    if name:
        out["name"] = name

    # First ComponentEntry's ModuleName is conventionally userSetup.py
    for entry in root.iter("ComponentEntry"):
        module_name = entry.get("ModuleName") or entry.get("modulename")
        if module_name:
            out["user_setup"] = module_name.lstrip("./").replace("\\", "/")
            break

    return out


_MOD_HEADER = re.compile(
    r"^\+\s*(?:(?:MAYAVERSION|PLATFORM|LOCALE):\S+\s+)*([\w.\-]+)\s+([\w.\-]+)\s+(.+?)\s*$"
)
_MOD_OVERRIDE = re.compile(r"^([A-Za-z][\w-]*):\s*(.+?)\s*$")


def parse_mod_file(path):
    """Parse a ``*.mod`` file.

    Returns a dict with optional keys ``name``, ``version``, ``base`` (the
    ``+`` line's path component), and any of ``scripts`` / ``plug_ins`` /
    ``icons`` / ``presets`` if the .mod has explicit override lines (e.g.
    ``scripts: scripts``). Lenient on errors.
    """
    out = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return out

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("+"):
            m = _MOD_HEADER.match(line)
            if m and "name" not in out:
                out["name"] = m.group(1)
                out["version"] = m.group(2)
                out["base"] = m.group(3)
            continue
        m = _MOD_OVERRIDE.match(line)
        if m:
            key = m.group(1).lower().replace("-", "_")
            if key in ("scripts", "plug_ins", "icons", "presets",
                       "xbmlangpath", "maya_plug_in_path", "maya_script_path"):
                # Normalize known keys to our internal names
                norm = {
                    "xbmlangpath": "icons",
                    "maya_plug_in_path": "plug_ins",
                    "maya_script_path": "scripts",
                }.get(key, key)
                out[norm] = m.group(2)
    return out


def detect(folder):
    """High-level detection helper used by the AddDialog.

    Returns a dict with at least ``is_module: bool``. When True, may also
    contain ``name`` (suggested package name) and ``user_setup`` (relative
    path) so the caller can prefill UI fields.
    """
    pkg_contents, mod_files = find_module_files(folder)
    if not (pkg_contents or mod_files):
        return {"is_module": False}

    info = {"is_module": True}
    if pkg_contents:
        parsed = parse_package_contents(pkg_contents)
        if parsed.get("name"):
            info["name"] = parsed["name"]
        if parsed.get("user_setup"):
            info["user_setup"] = parsed["user_setup"]
    if mod_files and "name" not in info:
        parsed = parse_mod_file(mod_files[0])
        if parsed.get("name"):
            info["name"] = parsed["name"]
    if "name" not in info:
        info["name"] = os.path.basename(os.path.normpath(folder))
    return info
