"""Resolve the display name shown in the UI for a package.

Source-of-truth order for v4.0:

1. My Tools (``source="local"``): ``installed_entry.display_name`` is the
   SoT — the user typed it in the Add / Edit dialog.
2. Registry-installed: ``registry_data.display_name`` is the SoT —
   the package author chose it at publish time.
3. Fall back to the bare package id / name.

The shape mirrors :mod:`carton.core.entry_point_resolver` so callers can
treat them symmetrically.
"""

from carton.core.install_state import is_pure_local


def resolve_display_name(pkg_id, installed_entry=None, registry_data=None):
    """Return the human-friendly display name to render in the UI."""
    if installed_entry and is_pure_local(installed_entry):
        name = installed_entry.get("display_name")
        if name:
            return name

    if registry_data:
        name = registry_data.get("display_name")
        if name:
            return name

    if installed_entry:
        # Fall back to whatever's on the entry — covers legacy installed
        # entries that still carry display_name even though the registry
        # is missing.
        name = installed_entry.get("display_name")
        if name:
            return name
        if installed_entry.get("name"):
            return installed_entry["name"]

    return pkg_id
