"""Tests for :func:`carton.ui.i18n.resolve_localized`.

Read side of the localized-description plumbing — flattens a manifest
field (plain string or locale dict) to a display string given the
active Carton language. Widget tests for the write side live in
``test_localized_description_widget.py``.
"""

import pytest

from carton.ui.i18n import resolve_localized, set_language


@pytest.fixture(autouse=True)
def _restore_language():
    """Each test runs in a clean language state and leaves the global as
    English so unrelated tests aren't affected by ordering."""
    set_language("en")
    yield
    set_language("en")


def test_plain_string_passes_through():
    assert resolve_localized("hello") == "hello"


def test_dict_resolves_to_active_language():
    set_language("ja")
    assert resolve_localized({"en": "Hi", "ja": "やあ"}) == "やあ"


def test_dict_falls_back_to_english_when_active_missing():
    set_language("ja")
    assert resolve_localized({"en": "Hi"}) == "Hi"


def test_dict_falls_back_to_first_string_when_neither_present():
    set_language("ja")
    assert resolve_localized({"fr": "salut"}) == "salut"


def test_region_suffix_matches_then_falls_back_to_stem():
    # Exact region wins over the stem
    assert resolve_localized({"en-US": "us", "en": "en"}, language="en-US") == "us"
    # Region missing → stem fallback
    assert resolve_localized({"en": "stem"}, language="en-US") == "stem"


def test_dict_resolves_arbitrary_locales():
    """The resolver isn't en/ja-specific — any string-keyed dict works."""
    assert resolve_localized({"zh": "你好", "fr": "salut"}, language="zh") == "你好"
    assert resolve_localized({"de": "hallo", "ko": "안녕"}, language="ko") == "안녕"


def test_empty_dict_returns_empty_string():
    assert resolve_localized({}) == ""


def test_malformed_value_returns_empty_string():
    assert resolve_localized(None) == ""
    assert resolve_localized(123) == ""
    assert resolve_localized([]) == ""


def test_explicit_language_overrides_global():
    set_language("ja")
    # Caller forcing "en" gets English regardless of the global.
    assert resolve_localized({"en": "Hi", "ja": "やあ"}, language="en") == "Hi"


def test_non_string_locale_value_skipped():
    """A dict with a non-string value for the requested locale skips that
    entry rather than raising — manifests can be malformed in the wild."""
    set_language("ja")
    assert resolve_localized({"en": "Hi", "ja": ["wrong"]}) == "Hi"
