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
        A dict — possibly empty if no entry point can be determined.
    """
    if package_dir and os.path.isdir(package_dir):
        inner = _read_inner_entry_point(package_dir)
        if inner is not None:
            return inner

    if installed_entry:
        ep = installed_entry.get("entry_point")
        if ep:
            return ep

    if registry_data:
        ep = registry_data.get("entry_point")
        if ep:
            return ep

    return {}


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
