"""UUID identity helpers — concept-neutral, used by catalogue / registry alike.

Each catalogue.json (and the v4.0 registry.json it succeeds) carries a
UUID v4 to identify itself across local + remote mirrors. The field
name differs by schema version (``registry_id`` in v4.0,
``catalogue_id`` in v5.0), but the validation rules are identical —
this module exposes those rules without being tied to either name.
Callers pick the field name they need at the call site.

Distinct from :mod:`carton.core.identity`, which deals with package
``namespace/name`` slugging — different concept, different helpers.
"""

import re
import uuid


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def new_uuid():
    """Return a fresh lowercase UUID v4 string."""
    return str(uuid.uuid4())


def is_valid_uuid(value):
    """True iff ``value`` is a well-formed lowercase UUID string."""
    if not value:
        return False
    return bool(_UUID_RE.match(str(value).strip().lower()))


def read_uuid(d, key):
    """Extract and validate a UUID from ``d[key]``. Empty string if missing/invalid."""
    if not d:
        return ""
    raw = d.get(key, "") or ""
    raw = raw.strip().lower()
    return raw if is_valid_uuid(raw) else ""


def stamp_uuid(d, key):
    """Ensure ``d[key]`` carries a valid UUID.

    Returns ``(uuid, was_new)``. If the dict already has a valid value
    under ``key`` it is returned untouched; otherwise a fresh UUID is
    written in place.
    """
    existing = read_uuid(d, key)
    if existing:
        return existing, False
    new_id = new_uuid()
    d[key] = new_id
    return new_id, True
