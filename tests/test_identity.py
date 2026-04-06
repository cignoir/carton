"""Tests for namespace/name identity helpers."""

import pytest

from carton.core.identity import (
    InvalidIdentityError,
    make_pkg_id,
    split_pkg_id,
    is_pkg_id,
    validate_namespace,
    validate_name,
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
