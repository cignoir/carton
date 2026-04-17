"""Registry identity helpers (UUID).

Each ``registry.json`` carries an optional ``registry_id`` (UUID v4) that acts
as the canonical identity of a logical registry. A local ``registry.json`` and
its remote HTTP mirror are "the same registry" when their ids match — publish
and duplicate detection use this to route writes to the correct local mirror
instead of growing unrelated entries.

Missing ids are treated as "not yet stamped", not invalid. Carton stamps them
on the first write it makes to a registry.
"""

import re
import uuid


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def new_registry_id():
    """Return a fresh lowercase UUID v4 string."""
    return str(uuid.uuid4())


def is_valid_registry_id(value):
    """True iff ``value`` is a well-formed lowercase UUID string."""
    if not value:
        return False
    return bool(_UUID_RE.match(str(value).strip().lower()))


def read_registry_id(registry_dict):
    """Extract and validate the ``registry_id`` from a loaded registry dict.

    Returns the lowercase UUID string, or ``""`` if missing / malformed.
    """
    if not registry_dict:
        return ""
    raw = registry_dict.get("registry_id", "")
    raw = (raw or "").strip().lower()
    return raw if is_valid_registry_id(raw) else ""


def stamp_registry_id(registry_dict):
    """Ensure ``registry_dict`` carries a valid ``registry_id``.

    Returns ``(id, was_new)``. If the dict already has a valid id it is
    returned untouched; otherwise a fresh UUID is written in place.
    """
    existing = read_registry_id(registry_dict)
    if existing:
        return existing, False
    new_id = new_registry_id()
    registry_dict["registry_id"] = new_id
    return new_id, True
