"""Tests for :class:`carton.ui._dialog_widgets.LocalizedDescriptionInput`.

The write side of the localized-description plumbing — a
variable-length list of ``(locale, text)`` rows. The widget is locale
agnostic: any ISO-639-1 code accepted by the package schema is editable
here, the en/ja split was an early-draft mistake.

Skipped at collection time on environments without PySide6 +
pytest-qt; the resolver tests in ``test_localized_description.py``
still run regardless.
"""

import pytest

# Module-level skip — no qtbot fixture, no point collecting these tests.
pytest.importorskip("PySide6", reason="UI widget tests require PySide6")
pytest.importorskip("pytestqt", reason="UI widget tests require pytest-qt")

from carton.ui._dialog_widgets import LocalizedDescriptionInput
from carton.ui.i18n import set_language


@pytest.fixture(autouse=True)
def _restore_language():
    set_language("en")
    yield
    set_language("en")


@pytest.fixture
def widget(qtbot):
    w = LocalizedDescriptionInput()
    qtbot.addWidget(w)
    return w


def _codes(w):
    return [r.locale_input.text() for r in w._rows]


def _texts(w):
    return [r.text_input.text() for r in w._rows]


def test_load_string_creates_one_default_locale_row(widget):
    widget.set_value("plain text")
    assert _codes(widget) == ["en"]
    assert _texts(widget) == ["plain text"]


def test_load_dict_one_row_per_key(widget):
    widget.set_value({"en": "Hi", "ja": "やあ", "fr": "Salut"})
    assert _codes(widget) == ["en", "ja", "fr"]
    assert _texts(widget) == ["Hi", "やあ", "Salut"]


def test_save_empty_returns_empty_string(widget):
    widget.set_value("")
    for r in widget._rows:
        r.text_input.clear()
    assert widget.get_value() == ""


def test_save_default_locale_only_collapses_to_plain_string(widget):
    """An en-only manifest stays a plain string for backward compat."""
    widget.set_value("only english")
    assert widget.get_value() == "only english"


def test_save_non_default_locale_only_returns_dict(widget):
    """A single non-default locale stays explicit so we don't claim it's
    the all-purpose default."""
    widget.set_value({"ja": "日本語のみ"})
    assert widget.get_value() == {"ja": "日本語のみ"}


def test_save_multiple_locales_returns_dict(widget):
    widget.set_value({"en": "Hi", "ja": "やあ"})
    assert widget.get_value() == {"en": "Hi", "ja": "やあ"}


def test_round_trips_arbitrary_locales(widget):
    """The widget is locale-agnostic — anything string-keyed survives."""
    payload = {"en": "Hi", "ja": "やあ", "fr": "Salut", "zh-TW": "你好"}
    widget.set_value(payload)
    assert widget.get_value() == payload


def test_clearing_row_text_drops_that_locale(widget):
    widget.set_value({"en": "Hi", "ja": "やあ"})
    for row in widget._rows:
        if row.locale_input.text() == "ja":
            row.text_input.clear()
    assert widget.get_value() == "Hi"


def test_remove_button_drops_row(widget):
    widget.set_value({"en": "Hi", "ja": "やあ"})
    for row in list(widget._rows):
        if row.locale_input.text() == "ja":
            row.remove_btn.click()
            break
    assert _codes(widget) == ["en"]
    assert widget.get_value() == "Hi"


def test_add_button_appends_blank_row(widget):
    widget.set_value({"en": "Hi"})
    initial = len(widget._rows)
    widget._add_btn.click()
    assert len(widget._rows) == initial + 1
    # New row's text is empty so it doesn't pollute get_value.
    assert widget.get_value() == "Hi"


def test_add_button_suggests_unused_locale(widget):
    """Adding a row when en is already used should pick a different code
    so the user doesn't have to retype to avoid a collision."""
    widget.set_value({"en": "Hi"})
    set_language("ja")
    widget._add_btn.click()
    new_code = widget._rows[-1].locale_input.text()
    assert new_code != "en"
    assert new_code  # something was suggested


def test_set_value_resets_rows(widget):
    """Replacing the value should fully clear prior rows — including
    locales that wouldn't appear in the new value."""
    widget.set_value({"en": "Hi", "fr": "Salut", "de": "Hallo"})
    widget.set_value({"en": "Bonjour"})
    assert widget.get_value() == "Bonjour"
    assert _codes(widget) == ["en"]


def test_default_locale_can_be_overridden(qtbot):
    """A studio that wants Japanese as the canonical default can pass it
    in — single-ja manifests then collapse to a plain string instead of
    being wrapped in a {ja: ...} dict."""
    w = LocalizedDescriptionInput(default_locale="ja")
    qtbot.addWidget(w)
    w.set_value("only japanese")
    assert _codes(w) == ["ja"]
    assert w.get_value() == "only japanese"
