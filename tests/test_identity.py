"""Tests for namespace/name identity helpers."""

import pytest

from carton.core.identity import (
    InvalidIdentityError,
    make_pkg_id,
    split_pkg_id,
    is_pkg_id,
    validate_namespace,
    validate_name,
    slugify_namespace,
    slugify_name,
)


def test_make_pkg_id_normalizes_case():
    assert make_pkg_id("MyStudio", "Rigger") == "mystudio/rigger"


def test_split_pkg_id():
    assert split_pkg_id("mystudio/rigger") == ("mystudio", "rigger")


def test_is_pkg_id_true_for_valid():
    assert is_pkg_id("mystudio/rigger")


def test_is_pkg_id_false_for_bare_name():
    assert not is_pkg_id("rigger")


def test_invalid_namespace_raises():
    with pytest.raises(InvalidIdentityError):
        validate_namespace("UPPER!")


def test_too_short_namespace_raises():
    with pytest.raises(InvalidIdentityError):
        validate_namespace("a")


def test_valid_name_with_underscore_ok():
    assert validate_name("quick_rename") == "quick_rename"


class TestSlugify:
    def test_pascal_case(self):
        assert slugify_name("AriMirror") == "ari-mirror"

    def test_camel_case(self):
        assert slugify_name("quickRename") == "quick-rename"

    def test_consecutive_caps_kept_together(self):
        assert slugify_name("AriUVScale") == "ari-uv-scale"

    def test_spaces_become_hyphens(self):
        assert slugify_name("Quick Rename") == "quick-rename"

    def test_underscore_preserved_in_name(self):
        assert slugify_name("my_tool") == "my_tool"

    def test_underscore_becomes_hyphen_in_namespace(self):
        assert slugify_namespace("my_studio") == "my-studio"

    def test_collapses_repeated_separators(self):
        assert slugify_name("foo   bar---baz") == "foo-bar-baz"

    def test_strips_leading_and_trailing_hyphens(self):
        assert slugify_name("--Foo--") == "foo"

    def test_drops_disallowed_chars(self):
        assert slugify_name("Tool 2.0!") == "tool-2-0"

    def test_empty_input_returns_empty(self):
        assert slugify_name("") == ""
        assert slugify_namespace("   ") == ""

    def test_already_canonical_unchanged(self):
        assert slugify_name("ari-mirror") == "ari-mirror"
        assert slugify_namespace("mystudio") == "mystudio"
