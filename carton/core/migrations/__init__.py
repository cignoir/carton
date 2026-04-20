"""Schema migration helpers — v0.3.x (schema v3.x) → v0.4.0 (schema v4.0).

Carton 0.4.0 collapses the registry / installed metadata model — see
``docs/schema-migration.md`` for the field-by-field rationale. The runtime
auto-migrates older files on first read and backs up the original next to
the original file with a ``.bak-v0.3.<timestamp>`` suffix.

Migrations are idempotent: data already at v4.0 passes through unchanged
and no backup is taken.
"""

import json
import os
import shutil
import time

from carton.core.migrations.installed import (
    INSTALLED_SCHEMA_VERSION,
    migrate_installed_data,
)
from carton.core.migrations.registry import (
    REGISTRY_SCHEMA_VERSION,
    migrate_registry_data,
)
from carton.core.migrations.catalogue import (
    CATALOGUE_FILENAME,
    CATALOGUE_SCHEMA_VERSION,
    LEGACY_REGISTRY_FILENAME,
    migrate_local_registry_file_to_catalogue,
    migrate_registry_to_catalogue,
)


__all__ = [
    "CATALOGUE_FILENAME",
    "CATALOGUE_SCHEMA_VERSION",
    "INSTALLED_SCHEMA_VERSION",
    "LEGACY_REGISTRY_FILENAME",
    "REGISTRY_SCHEMA_VERSION",
    "make_backup",
    "migrate_installed_data",
    "migrate_installed_file",
    "migrate_local_registry_file",
    "migrate_local_registry_file_to_catalogue",
    "migrate_registry_data",
    "migrate_registry_to_catalogue",
]


def make_backup(path):
    """Copy ``path`` to a timestamped ``.bak-v0.3.<ms>`` sibling.

    Returns the backup path on success, ``""`` if the source doesn't exist
    or the copy fails. Best-effort — migration proceeds even if the backup
    cannot be taken (we'd rather migrate than refuse to start).
    """
    if not os.path.exists(path):
        return ""
    backup_path = "{}.bak-v0.3.{}".format(path, int(time.time() * 1000))
    try:
        shutil.copy2(path, backup_path)
        return backup_path
    except OSError:
        return ""


def migrate_installed_file(path):
    """Migrate ``installed.json`` on disk in place. Returns True if a write happened.

    No-op if the file is missing or already at v4.0. Backs up the original
    before overwriting.
    """
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    migrated, was_migrated = migrate_installed_data(data)
    if not was_migrated:
        return False
    make_backup(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(migrated, f, indent=2, ensure_ascii=False)
    return True


def migrate_local_registry_file(path):
    """Migrate a local ``registry.json`` on disk in place. Returns True if a write happened."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    migrated, was_migrated = migrate_registry_data(data)
    if not was_migrated:
        return False
    make_backup(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(migrated, f, indent=2, ensure_ascii=False)
    return True
