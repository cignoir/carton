"""Catalogue (v5.0) migration: v4.0 registry → v5.0 catalogue.

Field-level changes:

* ``schema_version`` ``"4.0"`` → ``"5.0"``.
* ``registry_id`` → ``catalogue_id`` (UUID preserved).
* Each package gains a top-level ``origin`` field. For migrated packages
  the origin is always ``{"type": "embedded", "versions": <existing>}``
  — bytes still live under the catalogue's ``packages/`` directory.
* Per-version metadata (``versions``, ``latest_version``) moves into
  ``origin.versions`` / ``origin.latest_version``.
* Catalogue-level ``display_name`` is added (defaults to empty) so UI
  has a friendly label without scanning packages.

Display-oriented package metadata (``display_name``, ``description``,
``icon``, ``tags``, ``entry_point``, ``type``, ``author``,
``first_published_*``) is preserved as siblings of ``origin`` so the UI
can render package cards without first downloading the artifact. The
artifact's inner ``package.json`` remains the runtime SoT — the catalogue
copy is a preview only.

Filenames also change:

* ``registry.json`` → ``catalogue.json``. The migrator writes the new
  file and renames the original to ``registry.json.bak-v0.4.<ms>`` so
  rollback is trivial. :func:`migrate_local_registry_file_to_catalogue`
  performs the on-disk rename + content rewrite.
"""

import json
import os
import time

from carton.core.registry_id import (
    is_valid_registry_id,
    new_registry_id,
)


CATALOGUE_SCHEMA_VERSION = "5.0"
CATALOGUE_FILENAME = "catalogue.json"
LEGACY_REGISTRY_FILENAME = "registry.json"


def migrate_registry_to_catalogue(data, stamp_id=True):
    """Migrate a parsed v4.x ``registry.json`` dict to a v5.0 catalogue dict.

    Returns ``(catalogue_dict, was_migrated)``. Idempotent: data already
    at v5.0 passes through with ``was_migrated=False``.

    ``stamp_id`` controls whether a missing ``catalogue_id`` gets a fresh
    UUID. Mirrors the behaviour of the v4.0 migrator — local writes
    stamp, remote-only reads pass ``stamp_id=False`` so mirror matching
    stays deterministic.
    """
    if not isinstance(data, dict):
        out = {
            "schema_version": CATALOGUE_SCHEMA_VERSION,
            "catalogue_id": new_registry_id() if stamp_id else "",
            "packages": {},
        }
        return out, True

    if data.get("schema_version") == CATALOGUE_SCHEMA_VERSION:
        # Already v5.0 — only stamp a missing id, leave the rest alone.
        if stamp_id and not is_valid_registry_id(data.get("catalogue_id")):
            out = dict(data)
            out["catalogue_id"] = new_registry_id()
            return out, True
        return data, False

    out = {
        "schema_version": CATALOGUE_SCHEMA_VERSION,
        "catalogue_id": _carry_catalogue_id(data, stamp_id=stamp_id),
    }
    if data.get("display_name"):
        out["display_name"] = data["display_name"]
    if data.get("last_updated"):
        out["last_updated"] = data["last_updated"]

    packages_in = data.get("packages") or {}
    packages_out = {}
    for pkg_id, pkg_data in packages_in.items():
        packages_out[pkg_id] = _migrate_package(pkg_data)
    out["packages"] = packages_out

    return out, True


def _carry_catalogue_id(registry_data, stamp_id):
    """Return the v5.0 catalogue_id, preserving the v4.0 registry_id when valid."""
    raw = registry_data.get("catalogue_id") or registry_data.get("registry_id") or ""
    raw = (raw or "").strip().lower()
    if is_valid_registry_id(raw):
        return raw
    return new_registry_id() if stamp_id else ""


def _migrate_package(pkg_data):
    """Convert a v4.x package entry into a v5.0 package entry.

    ``versions`` and ``latest_version`` move into ``origin``. Display
    metadata (display_name, description, icon, etc.) stays at the
    package level so the catalogue can render UI without downloading
    the artifact zip.
    """
    if not isinstance(pkg_data, dict):
        # Defensive: leave unrecognisable entries untouched so a partial
        # corruption doesn't cascade into "all packages disappeared".
        return pkg_data

    src = dict(pkg_data)
    versions = src.pop("versions", {}) or {}
    latest = src.pop("latest_version", "") or ""

    origin = {"type": "embedded", "versions": versions}
    if latest:
        origin["latest_version"] = latest

    # The v4.0 ``id`` field (legacy UUID-style) is no longer used —
    # packages are keyed solely by ``namespace/name``.
    src.pop("id", None)

    out = {"origin": origin}
    # Preserve display + provenance metadata as siblings of origin so the
    # UI has something to show pre-install. The inner package.json stays
    # the runtime SoT for entry_point / maya_versions / icon details.
    for field in (
        "namespace", "name", "display_name", "description", "type", "author",
        "icon", "tags", "platform", "entry_point",
        "first_published_by", "first_published_at",
    ):
        if field in src:
            out[field] = src[field]
    return out


def migrate_local_registry_file_to_catalogue(path):
    """Migrate a v4.x ``registry.json`` on disk to a v5.0 ``catalogue.json``.

    * Reads ``path`` (must end with ``registry.json`` or already
      ``catalogue.json``).
    * Writes the migrated content to ``catalogue.json`` in the same
      directory.
    * Renames the original ``registry.json`` to
      ``registry.json.bak-v0.4.<ms>`` for rollback.

    Returns the path of the new ``catalogue.json`` on success, ``""`` if
    no work was done (file missing, parse failure, or already v5.0 with
    a valid id and the catalogue.json file already exists).
    """
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""

    migrated, was_migrated = migrate_registry_to_catalogue(data)
    base_dir = os.path.dirname(os.path.abspath(path))
    catalogue_path = os.path.join(base_dir, CATALOGUE_FILENAME)

    # If we're given a registry.json that already has a sibling
    # catalogue.json, we treat catalogue.json as authoritative and only
    # back up the legacy file — we don't want to clobber a hand-edited
    # v5.0 file with a stale auto-migration.
    if os.path.basename(path).lower() == LEGACY_REGISTRY_FILENAME:
        if os.path.exists(catalogue_path) and not was_migrated:
            _backup_legacy_registry(path)
            return catalogue_path

    if not was_migrated and os.path.basename(path).lower() == CATALOGUE_FILENAME:
        # Already migrated and we were pointed at the catalogue.json
        # itself — nothing to do.
        return path

    with open(catalogue_path, "w", encoding="utf-8") as f:
        json.dump(migrated, f, indent=2, ensure_ascii=False)

    if os.path.basename(path).lower() == LEGACY_REGISTRY_FILENAME:
        _backup_legacy_registry(path)

    return catalogue_path


def _backup_legacy_registry(path):
    """Rename ``registry.json`` to ``registry.json.bak-v0.4.<ms>``."""
    backup = "{}.bak-v0.4.{}".format(path, int(time.time() * 1000))
    try:
        os.rename(path, backup)
    except OSError:
        # Best-effort: if the rename fails (e.g. path locked on Windows)
        # leave the original in place. The migrator already wrote the
        # new catalogue.json so the system stays usable.
        pass
    return backup
