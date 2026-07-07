"""Single authority for entry_point shapes: build, normalize, resolve.

The canonical tagged-union forms (mirrored by ``package.schema.json``):

* ``{"type": "python", "module": ..., "function": ...}``
* ``{"type": "mel", "script": ..., "procedure": ...}``
* ``{"type": "exec", "file": ...}``
* ``{"type": "plugin", "plugin_file": ..., ["command"|"ui_command"]: ...}``

Every producer (AddDialog, EditDialog) must go through the ``build_*``
constructors and every consumer (launcher, register) through
:func:`normalize_entry_point`, so legacy dialects live only inside this
module instead of leaking shape knowledge into each call site.

Resolution source-of-truth order (:func:`resolve_entry_point`):

1. If the package is registry-installed and the inner ``package.json``
   exists at ``packages/<ns>/<name>/package.json``, that is the SoT.
2. If the entry has an ``entry_point`` field saved in ``installed.json``
   (My Tools only — registry installs no longer write this), use it.
3. Fall back to whatever preview hint the registry carries.

Steps 2 and 3 cover the My Tools and "registry browsed but not installed"
cases respectively. The expensive disk read in step 1 is only done when
the bytes actually exist.
"""

import json
import os


class EntryPointError(ValueError):
    """Raised when an entry_point fails validation."""


def build_python(module, function="show"):
    """Canonical python entry: import ``module``, call ``function()``."""
    return {"type": "python", "module": module, "function": function or "show"}


def build_mel(script, procedure=""):
    """Canonical MEL entry: source ``script``, call ``procedure()``.

    ``procedure`` defaults to the script's stem — Maya convention names
    the global proc after the file.
    """
    proc = procedure or os.path.splitext(os.path.basename(script))[0]
    return {"type": "mel", "script": script, "procedure": proc}


def build_exec(file):
    """Canonical exec entry: run ``file`` top-level (no import contract)."""
    return {"type": "exec", "file": file}


def build_plugin(plugin_file, command="", ui_command=""):
    """Canonical plugin entry: load ``plugin_file``, optionally run a command.

    ``plugin_file`` is stored extension-less per the schema; a basename
    like ``"foo.mll"`` is accepted and trimmed. ``command`` is a Python
    statement executed after load, ``ui_command`` a MEL procedure name.
    """
    stem = plugin_file[:-4] if plugin_file.endswith(".mll") else plugin_file
    entry = {"type": "plugin", "plugin_file": stem}
    if command:
        entry["command"] = command
    if ui_command:
        entry["ui_command"] = ui_command
    return entry


def validate_entry_point(ep):
    """Normalize ``ep`` and check it is dispatchable; return the result.

    Raises :class:`EntryPointError` naming the missing piece. Only the
    four tagged-union types are accepted — maya_module's free-form
    ``{"command": ...}`` entries never pass through here (that type is
    dispatched by its handler, not the generic launcher).
    """
    entry = normalize_entry_point(ep)
    if not isinstance(entry, dict):
        raise EntryPointError(
            "entry_point must be an object, got {!r}".format(entry))
    ep_type = entry.get("type")
    required = {
        "python": ("module",),
        "mel": ("script", "procedure"),
        "exec": ("file",),
        "plugin": ("plugin_file",),
    }
    if ep_type not in required:
        raise EntryPointError(
            "entry_point has no usable 'type' (got {!r})".format(ep_type))
    for key in required[ep_type]:
        if not entry.get(key):
            raise EntryPointError(
                "entry_point type {!r} requires a non-empty {!r}".format(
                    ep_type, key))
    return entry


def resolve_entry_point(installed_entry, package_dir=None, registry_data=None):
    """Return the launch entry_point dict for a package.

    Args:
        installed_entry: ``installed.json`` entry dict (may be empty).
        package_dir: Absolute path to the extracted package directory, or
            None if the package isn't registry-installed.
        registry_data: The merged registry package dict, used as a final
            preview-hint fallback. May be None.

    Returns:
        A dict — possibly empty if no entry point can be determined. The
        result is normalised: legacy shapes (``"module:function"`` string,
        bare ``module``/``script`` dict without a ``type`` key) are upgraded
        to the current tagged-union form so downstream launchers can
        dispatch on ``type``.
    """
    if package_dir and os.path.isdir(package_dir):
        inner = _read_inner_entry_point(package_dir)
        if inner is not None:
            return normalize_entry_point(inner)

    if installed_entry:
        ep = installed_entry.get("entry_point")
        if ep:
            return normalize_entry_point(ep)

    if registry_data:
        ep = registry_data.get("entry_point")
        if ep:
            return normalize_entry_point(ep)

    return {}


def normalize_entry_point(ep):
    """Coerce a possibly-legacy entry_point into the tagged-union shape.

    Transforms:
      * ``"module:function"`` string → ``{"type":"python", "module":..., "function":...}``
      * dict without ``type`` but with ``module`` → ``{"type":"python", ...}``
      * dict without ``type`` but with ``script`` + ``procedure`` → ``{"type":"mel", ...}``
      * dict without ``type`` but with ``file`` ending in ``.mll`` → ``{"type":"plugin", ...}``
      * plugin dialect ``{"type":"plugin", "file": ...}`` (single-file
        registrations pre-0.5.9) → the schema's ``plugin_file`` key

    Anything already canonical passes through. Anything we can't
    classify is returned as-is so the launcher's own fall-through guard
    surfaces a clear error.
    """
    if isinstance(ep, str) and ":" in ep:
        mod, _, fn = ep.partition(":")
        mod = mod.strip()
        fn = fn.strip()
        if mod and fn:
            return {"type": "python", "module": mod, "function": fn}
        return ep
    if not isinstance(ep, dict) or not ep:
        return ep
    if ep.get("type"):
        return _canonicalize_plugin(ep)
    promoted = dict(ep)
    if ep.get("module"):
        promoted["type"] = "python"
        promoted.setdefault("function", ep.get("function") or "show")
        return promoted
    if ep.get("script") and ep.get("procedure"):
        promoted["type"] = "mel"
        return promoted
    file_hint = ep.get("file", "")
    if file_hint.endswith(".mll"):
        promoted["type"] = "plugin"
        return _canonicalize_plugin(promoted)
    return ep


def _canonicalize_plugin(ep):
    """Rename a plugin entry's legacy ``file`` key to ``plugin_file``.

    The value is kept verbatim (extension and all) — the launcher
    tolerates both bare and ``.mll`` names, and rewriting values here
    would silently change what legacy installed.json entries point at.
    """
    if ep.get("type") != "plugin" or "file" not in ep or ep.get("plugin_file"):
        return ep
    fixed = dict(ep)
    fixed["plugin_file"] = fixed.pop("file")
    return fixed


def _read_inner_entry_point(package_dir):
    """Read ``<package_dir>/package.json`` and return its entry_point.

    Returns ``None`` when the file is missing or unreadable so callers
    can fall through to the next layer. Returns the entry_point dict
    (possibly empty) when the file parsed successfully — even an empty
    entry_point is authoritative if package.json says so.
    """
    inner_path = os.path.join(package_dir, "package.json")
    if not os.path.exists(inner_path):
        return None
    try:
        with open(inner_path, "rb") as f:
            data = json.loads(f.read().decode("latin-1"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    ep = data.get("entry_point")
    if ep is None:
        return {}
    return ep
