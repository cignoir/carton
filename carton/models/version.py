"""Semantic versioning."""

import re


class Version:
    """Semantic Version (MAJOR.MINOR.PATCH) comparison and parsing."""

    _PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

    def __init__(self, major, minor, patch):
        self.major = major
        self.minor = minor
        self.patch = patch

    @classmethod
    def parse(cls, version_str):
        """Parse from a string. Raises ValueError if invalid."""
        m = cls._PATTERN.match(version_str)
        if not m:
            raise ValueError("Invalid version: {}".format(version_str))
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    def _tuple(self):
        return (self.major, self.minor, self.patch)

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._tuple() == other._tuple()

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._tuple() < other._tuple()

    def __le__(self, other):
        return self == other or self < other

    def __gt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._tuple() > other._tuple()

    def __ge__(self, other):
        return self == other or self > other

    def __repr__(self):
        return "Version({}.{}.{})".format(self.major, self.minor, self.patch)

    def __str__(self):
        return "{}.{}.{}".format(self.major, self.minor, self.patch)


def next_free_patch(version_str, taken):
    """Return the first ``MAJOR.MINOR.PATCH`` after ``version_str`` not in ``taken``.

    Used when a publish collides with a version already in the
    catalogue: the answer the author almost always wants is "the next
    patch", and walking past the ones already published means a
    re-collision can't send them round the loop a second time.

    ``taken`` is any container of version strings. Returns ``None`` if
    ``version_str`` isn't parseable semver — there is no sensible
    successor to a version we can't read, and guessing one would publish
    under a number the author never chose.
    """
    try:
        current = Version.parse(version_str)
    except (ValueError, TypeError):
        return None
    taken = set(taken or ())
    candidate = Version(current.major, current.minor, current.patch + 1)
    while str(candidate) in taken:
        candidate = Version(candidate.major, candidate.minor,
                            candidate.patch + 1)
    return str(candidate)


def semver_sort_key(version_str):
    """Sort key ordering version strings numerically (0.10.0 > 0.9.0).

    Lexicographic ordering breaks as soon as any component hits two
    digits. Unparseable strings rank below every valid semver and fall
    back to string order among themselves, so a stray tag never beats a
    real release.
    """
    try:
        v = Version.parse(version_str)
        return (1, v.major, v.minor, v.patch, version_str)
    except ValueError:
        return (0, 0, 0, 0, version_str)
