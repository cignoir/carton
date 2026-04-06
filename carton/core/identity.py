"""Package identity helpers (namespace/name).

Carton's canonical identifier form is lowercase a-z / 0-9 / hyphens (and
underscores for ``name``). Most users — Maya artists writing tools — will
naturally type things like ``AriMirror`` or ``Quick Rename``. Rather than
rejecting them, we slugify on input and show the canonical form in the UI.
"""

import re

_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")

# camelCase / PascalCase boundary patterns:
#   "AriMirror"      -> insert hyphen before each "Mirror"
#   "AriUVScale"     -> "Ari-UV-Scale" (consecutive caps stay together)
_CAMEL_BOUNDARY_1 = re.compile(r"(.)([A-Z][a-z]+)")  # "AriM" + "irror"
_CAMEL_BOUNDARY_2 = re.compile(r"([a-z0-9])([A-Z])")  # "iU" -> "i-U"


class InvalidIdentityError(ValueError):
    """Raised when namespace or name fails validation."""


def normalize(value):
    """Lowercase and strip a candidate identifier."""
    return (value or "").strip().lower()


def _slugify(text, allow_underscore):
    """Convert arbitrary user text into a lowercase slug.

    - Splits camelCase / PascalCase at boundaries (``AriMirror`` -> ``ari-mirror``)
    - Replaces any run of disallowed characters with a single hyphen
    - Lowercases
    - Collapses repeated hyphens and strips them from the ends

    ``allow_underscore`` keeps existing underscores in ``name`` (Python module
    style); for ``namespace`` they are converted to hyphens.
    """
    if not text:
        return ""
    s = text.strip()
    # Split camelCase boundaries
    s = _CAMEL_BOUNDARY_1.sub(r"\1-\2", s)
    s = _CAMEL_BOUNDARY_2.sub(r"\1-\2", s)
    s = s.lower()
    # Drop / replace anything outside the allowed alphabet
    if allow_underscore:
        s = re.sub(r"[^a-z0-9_-]+", "-", s)
    else:
        s = re.sub(r"[^a-z0-9-]+", "-", s)
    # Collapse hyphen runs and strip ends
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s


def slugify_namespace(text):
    """Slugify a candidate namespace. May still need :func:`validate_namespace`."""
    return _slugify(text, allow_underscore=False)


def slugify_name(text):
    """Slugify a candidate package name. May still need :func:`validate_name`."""
    return _slugify(text, allow_underscore=True)


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
