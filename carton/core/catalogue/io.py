"""Read / write a catalogue file with v5 migration baked in.

Callers should never see a v4.0 ``registry.json`` shape — by the time
the dict reaches business logic the migrator has run. Centralising the
``open + json.load + migrate_registry_to_catalogue`` triplet here means
the migration is invisible to readers; they get a v5 dict no matter
what was on disk.

For pure in-memory work (e.g. linting a remote catalogue payload that
was already fetched), call :func:`carton.core.migrations.migrate_registry_to_catalogue`
directly — this module is for the on-disk path.
"""

import json
import os

from carton.core.migrations import (
    CATALOGUE_FILENAME,
    LEGACY_REGISTRY_FILENAME,
    migrate_local_registry_file_to_catalogue,
    migrate_registry_to_catalogue,
)


__all__ = ["read_catalogue_dict", "write_catalogue_dict"]


def read_catalogue_dict(path, stamp_id=True, auto_migrate_file=True):
    """Read a catalogue file and return ``(data, resolved_path)``.

    ``data`` is always a v5.0 catalogue dict (``schema_version == "5.0"``).
    ``resolved_path`` is the path actually read — when
    ``auto_migrate_file`` is True and ``path`` pointed at a legacy
    ``registry.json``, this is the rewritten ``catalogue.json`` sibling.

    A missing file returns ``({}, "")`` rather than raising; callers
    that need to distinguish should check ``resolved_path``. A parse
    failure also returns the empty pair.
    """
    if not path or not os.path.exists(path):
        return {}, ""

    if auto_migrate_file and os.path.basename(path).lower() == LEGACY_REGISTRY_FILENAME:
        migrated = migrate_local_registry_file_to_catalogue(path)
        if migrated:
            path = migrated

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}, path

    data, _ = migrate_registry_to_catalogue(raw, stamp_id=stamp_id)
    return data, path


def write_catalogue_dict(path, data):
    """Write ``data`` (already v5) to ``path``, atomic via temp + replace."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def catalogue_filename_for(dir_path):
    """Return the conventional catalogue.json path inside ``dir_path``."""
    return os.path.join(dir_path, CATALOGUE_FILENAME)
