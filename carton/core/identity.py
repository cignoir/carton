"""Package identity helpers (namespace/name)."""

import re

_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


class InvalidIdentityError(ValueError):
    """Raised when namespace or name fails validation."""


def normalize(value):
    """Lowercase and strip a candidate identifier."""
    return (value or "").strip().lower()


def validate_namespace(namespace):
    """Validate a namespace; return the normalized form."""
    ns = normalize(namespace)
    if not ns:
        raise InvalidIdentityError("namespace is required")
    if not _NAMESPACE_RE.match(ns):
        raise InvalidIdentityError(
            "invalid namespace {!r}: must be 2-32 chars, lowercase a-z 0-9 -".format(namespace)
        )
    return ns


def validate_name(name):
    """Validate a package name; return the normalized form."""
    nm = normalize(name)
    if not nm:
        raise InvalidIdentityError("name is required")
    if not _NAME_RE.match(nm):
        raise InvalidIdentityError(
            "invalid name {!r}: must be 2-32 chars, lowercase a-z 0-9 _ -".format(name)
        )
    return nm


def make_pkg_id(namespace, name):
    """Build a canonical 'namespace/name' package id."""
    return "{}/{}".format(validate_namespace(namespace), validate_name(name))


def split_pkg_id(pkg_id):
    """Split 'namespace/name' into a (namespace, name) tuple. Returns (None, None) on bad input."""
    if not pkg_id or "/" not in pkg_id:
        return (None, None)
    ns, _, nm = pkg_id.partition("/")
    return (ns, nm)


def is_pkg_id(value):
    """Whether the given string looks like a 'namespace/name' identifier."""
    ns, nm = split_pkg_id(value)
    if not ns or not nm:
        return False
    return bool(_NAMESPACE_RE.match(ns) and _NAME_RE.match(nm))
