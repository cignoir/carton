"""Folder-scan and package-type detection (Maya-independent).

The same logic the Add dialog uses to decide what kind of package a folder
contains. Lifted out of ``carton.ui.add_dialog`` so the CLI lint command
can call it without pulling Qt or Maya.

The shape of ``scan_folder``'s return dict is preserved exactly so the UI
layer can keep using it as the source-of-truth detector.
"""

import json
import os
import re

from carton.core.maya_module_detect import detect as detect_maya_module


# Top-level folders that should be ignored during the extension scan
# because they ship with third-party Python files that are not part of
# the user's package — including them flips the type to python_package
# and breaks the import target. Real-world cases:
#   - devkits/         Autodesk Maya devkit (~thousands of .py)
#   - build/, dist/    CMake / setuptools build outputs
#   - node_modules/    Node.js packages
#   - .git/, .svn/     VCS metadata
#   - .venv/, venv/    Python virtualenvs
#   - __pycache__/     Bytecode cache (also irrelevant)
VENDOR_DIRS = frozenset({
    "devkits",
    "build",
    "dist",
    "node_modules",
    ".git",
    ".svn",
    ".hg",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
})


def scan_folder(folder_path):
    """Auto-detect package information from a folder.

    Returns a dict with at least ``name``, ``display_name``, ``type``,
    ``function``, ``is_folder`` keys. Additional keys appear depending on
    what was detected (``has_package_json``, ``is_maya_module``, ``icon``,
    ``description``, ``version``, ``author``, ``namespace``, ``home_origin``,
    ``entry_point``, ``include_compiled``, ``vendor_dirs_seen``).

    ``vendor_dirs_seen`` is the list of vendor-style directory names found
    at the top level — surfaced so callers (the lint command) can warn the
    user that these will be picked up by the auto-type scan unless excluded.
    """
    info = {
        "name": os.path.basename(folder_path).lower().replace("-", "_").replace(" ", "_"),
        "display_name": os.path.basename(folder_path),
        "type": "python_package",
        "function": "show",
        "is_folder": True,
    }

    # Read from package.json if it exists
    pkg_json = os.path.join(folder_path, "package.json")
    if os.path.exists(pkg_json):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            info["name"] = data.get("name", info["name"])
            info["display_name"] = data.get("display_name", info["display_name"])
            info["type"] = data.get("type", info["type"])
            ep = data.get("entry_point", {})
            if isinstance(ep, dict):
                info["function"] = ep.get("function", ep.get("procedure", "show"))
            if data.get("namespace"):
                info["namespace"] = data["namespace"]
            if data.get("home_origin"):
                info["home_origin"] = data["home_origin"]
            info["icon"] = data.get("icon", "")
            info["description"] = data.get("description", "")
            info["version"] = data.get("version", "0.0.0")
            info["author"] = data.get("author", "")
            info["has_package_json"] = True
            info["entry_point"] = data.get("entry_point", {})
            return info
        except (json.JSONDecodeError, OSError):
            pass

    # Detect Maya module (Application Package or .mod) before falling back
    # to the extension scan. package.json above already short-circuited.
    mod_info = detect_maya_module(folder_path)
    if mod_info.get("is_module"):
        info["type"] = "maya_module"
        info["is_maya_module"] = True
        info["name"] = mod_info.get("name") or info["name"]
        info["display_name"] = mod_info.get("name") or info["display_name"]
        info["entry_point"] = {}
        return info

    # Detect functions from __init__.py
    init_py = os.path.join(folder_path, info["name"], "__init__.py")
    if not os.path.exists(init_py):
        # May be directly in the folder
        init_py = os.path.join(folder_path, "__init__.py")
    if os.path.exists(init_py):
        info["function"] = _detect_function_in_file(init_py) or "show"

    # Detect MEL / Plugin via priority: any Python source in the tree
    # wins (because Python tooling may legitimately ship .mll helpers
    # alongside it). Only fall back to plugin / mel_script when there
    # is no Python at all.
    extensions = set()
    vendor_seen = []
    try:
        for entry in os.listdir(folder_path):
            full = os.path.join(folder_path, entry)
            if os.path.isdir(full) and entry in VENDOR_DIRS:
                vendor_seen.append(entry)
    except OSError:
        pass

    for root, dirs, files in os.walk(folder_path):
        # Prune vendor dirs in-place so we don't recurse into them
        dirs[:] = [d for d in dirs if d not in VENDOR_DIRS]
        for f in files:
            extensions.add(os.path.splitext(f)[1].lower())

    has_py = ".py" in extensions
    has_pyc = ".pyc" in extensions
    if has_py or has_pyc:
        info["type"] = "python_package"
    elif ".mll" in extensions:
        info["type"] = "plugin"
    elif ".mel" in extensions:
        info["type"] = "mel_script"

    # Auto-include .pyc when there is no .py source to ship.
    info["include_compiled"] = has_pyc and not has_py
    info["vendor_dirs_seen"] = vendor_seen

    return info


def _detect_function_in_file(path):
    """Detect a callable function from a Python file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        for name in ["show", "run", "main", "execute"]:
            if re.search(r"^def {}\s*\(".format(name), content, re.MULTILINE):
                return name

        match = re.search(r"^def ([a-zA-Z][a-zA-Z0-9_]*)\s*\(", content, re.MULTILINE)
        if match:
            return match.group(1)
    except (OSError, UnicodeDecodeError):
        pass
    return None
