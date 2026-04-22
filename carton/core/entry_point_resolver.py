"""Resolve the launch entry_point for an installed package.

Source-of-truth order for v4.0:

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

    Anything already carrying a ``type`` passes through. Anything we can't
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
        return ep
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
        return promoted
    return ep


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
