"""installed.json migration: v3.x → v4.0.

Field-level changes:

* ``source`` enum: ``"published"`` → ``"registry"`` (the bytes still live on
  disk; the My Tools side is reflected by ``local_path`` being non-empty).
  ``"local_script"`` → ``"local"``.
* ``entry_point``: dropped for ``source="registry"`` entries — the inner
  ``package.json`` shipped in the package zip is the single source of truth
  at launch time. Retained for ``source="local"`` (My Tools), which has no
  zip and therefore no inner package.json to read from.
* ``display_name``: dropped for ``source="registry"`` entries (registry
  becomes SoT). Retained for ``source="local"``.
* ``sha256``: dropped unconditionally. The registry's ``version_entry.sha256``
  is the SoT for the verified badge.
"""


INSTALLED_SCHEMA_VERSION = "4.0"


def migrate_installed_data(data):
    """Migrate a parsed installed.json dict to v4.0.

    Returns ``(migrated_dict, was_migrated)``. Idempotent: data already at
    v4.0 passes through with ``was_migrated=False``.
    """
    if not isinstance(data, dict):
        return {"schema_version": INSTALLED_SCHEMA_VERSION, "packages": {}}, True

    if data.get("schema_version") == INSTALLED_SCHEMA_VERSION:
        return data, False

    packages = data.get("packages") or {}
    migrated_packages = {}
    for pkg_id, entry in packages.items():
        migrated_packages[pkg_id] = _migrate_entry(entry)

    return {
        "schema_version": INSTALLED_SCHEMA_VERSION,
        "packages": migrated_packages,
    }, True


def _migrate_entry(entry):
    """Migrate a single installed.json package entry."""
    if not isinstance(entry, dict):
        return entry

    e = dict(entry)

    src = e.get("source", "registry")
    if src == "published":
        e["source"] = "registry"
    elif src == "local_script":
        e["source"] = "local"
    elif src not in ("registry", "local"):
        # Unknown legacy values: best-guess based on whether bytes exist on disk.
        e["source"] = "local" if not e.get("path") else "registry"

    is_local = (e.get("source") == "local")

    # SHA256 always dropped — registry version_entry.sha256 is the SoT.
    e.pop("sha256", None)

    if not is_local:
        # Registry-installed: zip's inner package.json carries entry_point /
        # display_name. Remove the duplicate copy stored at install time.
        e.pop("entry_point", None)
        e.pop("display_name", None)

    return e
