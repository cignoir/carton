"""installed.json entry classification helpers.

Centralised so every UI / core call site agrees on what "installed",
"My Tools", and "double-bound" mean. The on-disk form has only two
``source`` values now (``"registry"`` and ``"local"``) — the third leg
of the triangle (registry-installed AND My Tools-registered, formerly
``source="published"``) is expressed by ``source="registry"`` plus a
non-empty ``local_path``.
"""


def is_my_tools(entry):
    """True if the user has registered this entry in My Tools.

    Covers two cases:

    * pure My Tools (``source="local"``)
    * registry-installed but also bound to a local source path
      (``source="registry"`` with ``local_path``)
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("source") == "local":
        return True
    return bool(entry.get("local_path"))


def is_registry_installed(entry):
    """True if the registry zip's bytes are extracted on disk for this entry."""
    if not isinstance(entry, dict):
        return False
    return entry.get("source") == "registry" and bool(entry.get("path"))


def is_pure_local(entry):
    """True if the entry is My Tools only (no registry-installed bytes)."""
    if not isinstance(entry, dict):
        return False
    return entry.get("source") == "local"


def is_double_bound(entry):
    """True if the entry is registry-installed AND My Tools-registered.

    These are the entries that survive an uninstall-from-registry by
    being demoted to ``source="local"`` instead of being deleted.
    """
    if not isinstance(entry, dict):
        return False
    return (
        entry.get("source") == "registry"
        and bool(entry.get("local_path"))
        and bool(entry.get("path"))
    )
