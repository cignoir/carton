"""registry.json migration: v3.0 / v3.1 → v4.0.

Field-level changes:

* ``schema_version`` bumped to ``"4.0"``.
* ``registry_id`` is now required — auto-stamped if missing.
* ``icon``: legacy ``true`` (auto-resolve ``<name>.png``) becomes the literal
  string ``"@auto"``; ``false`` becomes ``null``.
"""

from carton.core.uuid_id import stamp_uuid


REGISTRY_SCHEMA_VERSION = "4.0"


def migrate_registry_data(data, stamp_id=True):
    """Migrate a parsed registry.json dict to v4.0.

    Returns ``(migrated_dict, was_migrated)``. Idempotent.

    ``stamp_id`` controls whether a missing ``registry_id`` gets a fresh
    UUID stamped in. Local registries should stamp (we're about to write
    back) but remote-only reads pass ``stamp_id=False`` — otherwise every
    fetch generates a different in-memory UUID and downstream mirror
    matching becomes nondeterministic.
    """
    if not isinstance(data, dict):
        out = {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "registry_id": "",
            "packages": {},
        }
        if stamp_id:
            stamp_uuid(out, "registry_id")
        return out, True

    needs_migration = (
        data.get("schema_version") != REGISTRY_SCHEMA_VERSION
        or (stamp_id and not data.get("registry_id"))
        or _has_legacy_icon(data)
    )
    if not needs_migration:
        return data, False

    out = dict(data)
    out["schema_version"] = REGISTRY_SCHEMA_VERSION
    if stamp_id:
        stamp_uuid(out, "registry_id")

    packages = out.get("packages") or {}
    new_packages = {}
    for pkg_id, pkg_data in packages.items():
        new_packages[pkg_id] = _migrate_package(pkg_data)
    out["packages"] = new_packages

    return out, True


def _has_legacy_icon(data):
    for pkg_data in (data.get("packages") or {}).values():
        if isinstance(pkg_data, dict) and isinstance(pkg_data.get("icon"), bool):
            return True
    return False


def _migrate_package(pkg_data):
    if not isinstance(pkg_data, dict):
        return pkg_data
    p = dict(pkg_data)
    icon = p.get("icon")
    if isinstance(icon, bool):
        p["icon"] = "@auto" if icon else None
    return p
