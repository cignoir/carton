"""Tests for the Version model."""

import pytest
from carton.models.version import Version, semver_sort_key


class TestVersionParse:
    def test_valid(self):
        v = Version.parse("1.2.3")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_zero(self):
        v = Version.parse("0.0.0")
        assert str(v) == "0.0.0"

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            Version.parse("1.2")

    def test_invalid_chars(self):
        with pytest.raises(ValueError):
            Version.parse("1.2.3-beta")


class TestVersionComparison:
    def test_equal(self):
        assert Version.parse("1.0.0") == Version.parse("1.0.0")

    def test_major(self):
        assert Version.parse("2.0.0") > Version.parse("1.9.9")

    def test_minor(self):
        assert Version.parse("1.1.0") > Version.parse("1.0.9")

    def test_patch(self):
        assert Version.parse("1.0.1") > Version.parse("1.0.0")

    def test_lt(self):
        assert Version.parse("0.9.0") < Version.parse("1.0.0")

    def test_le(self):
        assert Version.parse("1.0.0") <= Version.parse("1.0.0")
        assert Version.parse("1.0.0") <= Version.parse("1.0.1")

    def test_ge(self):
        assert Version.parse("1.0.1") >= Version.parse("1.0.0")
        assert Version.parse("1.0.0") >= Version.parse("1.0.0")


class TestVersionStr:
    def test_str(self):
        assert str(Version.parse("1.2.3")) == "1.2.3"

    def test_repr(self):
        assert repr(Version.parse("1.2.3")) == "Version(1.2.3)"


class TestSemverSortKey:
    def test_two_digit_components_sort_numerically(self):
        # Lexicographic order would put "0.9.0" last — the original bug
        # in the github-origin latest_version projection.
        versions = ["0.9.0", "0.10.0", "0.2.1"]
        assert max(versions, key=semver_sort_key) == "0.10.0"

    def test_full_ordering(self):
        versions = ["1.0.0", "0.10.0", "0.9.0", "10.0.0", "2.0.10", "2.0.9"]
        assert sorted(versions, key=semver_sort_key) == [
            "0.9.0", "0.10.0", "1.0.0", "2.0.9", "2.0.10", "10.0.0",
        ]

    def test_unparseable_never_beats_valid_semver(self):
        versions = ["zzz-tag", "0.1.0"]
        assert max(versions, key=semver_sort_key) == "0.1.0"

    def test_only_unparseable_falls_back_to_string_order(self):
        versions = ["beta", "alpha"]
        assert max(versions, key=semver_sort_key) == "beta"
