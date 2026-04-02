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
