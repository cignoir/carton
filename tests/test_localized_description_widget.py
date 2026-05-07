"""Tests for :class:`carton.ui._dialog_widgets.LocalizedDescriptionInput`.

The widget is a one-row description input with a language tab
switcher: clicking a tab swaps the input contents to that locale's
text. The previous draft stacked one row per locale and grew the
dialog vertically — these tests target the compact tab-based redesign.

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


# ---------------------------------------------------------------------------
# set_value: tab seeding
# ---------------------------------------------------------------------------


def test_load_string_creates_default_locale_tab(widget):
    widget.set_value("plain text")
    assert list(widget._strings.keys()) == ["en"]
    assert widget._strings["en"] == "plain text"
    assert widget._active == "en"
    assert widget._text_input.text() == "plain text"


def test_load_dict_one_tab_per_key(widget):
    widget.set_value({"en": "Hi", "ja": "やあ", "fr": "Salut"})
    assert list(widget._strings.keys()) == ["en", "ja", "fr"]
    assert set(widget._tab_buttons.keys()) == {"en", "ja", "fr"}
    # Active defaults to en (the default locale) when present
    assert widget._active == "en"
    assert widget._text_input.text() == "Hi"


def test_load_dict_without_default_locale_picks_first_key(widget):
    widget.set_value({"ja": "やあ", "fr": "Salut"})
    # No "en" present → fall back to whichever key the manifest had first
    assert widget._active == "ja"
    assert widget._text_input.text() == "やあ"


def test_load_empty_seeds_blank_default_locale(widget):
    widget.set_value("")
    assert widget._active == "en"
    assert widget._strings == {"en": ""}
    assert widget._text_input.text() == ""


# ---------------------------------------------------------------------------
# Tab clicking
# ---------------------------------------------------------------------------


def test_clicking_tab_swaps_input_contents(widget):
    widget.set_value({"en": "Hi", "ja": "やあ"})
    widget._on_tab_clicked("ja")
    assert widget._active == "ja"
    assert widget._text_input.text() == "やあ"
    # Active button is checked; previous one isn't
    assert widget._tab_buttons["ja"].isChecked()
    assert not widget._tab_buttons["en"].isChecked()


def test_typing_into_input_persists_in_active_locale(widget):
    """A switch back must show the latest text the user typed — even
    if they never blurred or hit save."""
    widget.set_value({"en": "Hi", "ja": ""})
    widget._on_tab_clicked("ja")
    widget._text_input.setText("こんにちは")
    widget._on_tab_clicked("en")
    assert widget._text_input.text() == "Hi"
    widget._on_tab_clicked("ja")
    assert widget._text_input.text() == "こんにちは"


def test_clicking_active_tab_does_not_uncheck_it(widget):
    """One tab must always be selected — clicking the active one is a
    no-op rather than turning the widget into a tabless ghost."""
    widget.set_value("Hi")
    # QPushButton-checkable normally toggles on second press; the
    # widget should reassert the checked state.
    widget._tab_buttons["en"].setChecked(False)
    widget._on_tab_clicked("en")
    assert widget._tab_buttons["en"].isChecked()


# ---------------------------------------------------------------------------
# Add / remove locale
# ---------------------------------------------------------------------------


def test_remove_locale_drops_tab_and_string(widget):
    widget.set_value({"en": "Hi", "ja": "やあ"})
    widget._remove_locale("ja")
    assert "ja" not in widget._strings
    assert "ja" not in widget._tab_buttons
    assert widget._active == "en"


def test_remove_active_locale_falls_back_to_first(widget):
    widget.set_value({"en": "Hi", "ja": "やあ"})
    widget._on_tab_clicked("ja")
    widget._remove_locale("ja")
    # Removing the active tab → switch to whatever's left
    assert widget._active == "en"
    assert widget._text_input.text() == "Hi"


def test_remove_last_locale_clears_text_but_keeps_tab(widget):
    """Letting the user remove the only remaining tab would leave the
    widget empty and unusable. Soft-clear instead."""
    widget.set_value("only english")
    widget._remove_locale("en")
    assert widget._strings == {"en": ""}
    assert widget._active == "en"
    assert widget._text_input.text() == ""


def test_internal_add_creates_tab_and_switches_to_it(widget):
    """Simulating what _on_add_clicked does after the prompt commits."""
    widget.set_value("Hi")
    widget._strings["ja"] = ""
    widget._active = "ja"
    widget._rebuild_tabs()
    widget._show_active()
    assert "ja" in widget._tab_buttons
    assert widget._active == "ja"
    assert widget._text_input.text() == ""


# ---------------------------------------------------------------------------
# get_value: round-trip rules
# ---------------------------------------------------------------------------


def test_save_default_locale_only_collapses_to_plain_string(widget):
    """Single-en manifests stay strings for backward compat."""
    widget.set_value("only english")
    assert widget.get_value() == "only english"


def test_save_non_default_locale_only_returns_dict(widget):
    """Single-ja stays a dict so we don't claim ja text is the
    all-purpose default."""
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


def test_save_empty_returns_empty_string(widget):
    widget.set_value("")
    assert widget.get_value() == ""


def test_clearing_active_input_drops_that_locale(widget):
    widget.set_value({"en": "Hi", "ja": "やあ"})
    widget._on_tab_clicked("ja")
    widget._text_input.clear()  # user erased the ja text
    assert widget.get_value() == "Hi"


def test_get_value_picks_up_unsaved_typing(widget):
    """The user might call get_value without first switching tabs —
    the input contents need to count even though textChanged already
    mirrored them, just so the contract is robust against signal
    blocking."""
    widget.set_value("")
    widget._text_input.setText("typed but not saved")
    assert widget.get_value() == "typed but not saved"


# ---------------------------------------------------------------------------
# State reset
# ---------------------------------------------------------------------------


def test_set_value_resets_prior_state(widget):
    """Replacing the value must fully drop locales the new value
    doesn't carry — otherwise an unrelated edit could resurrect a
    locale the new manifest never had."""
    widget.set_value({"en": "Hi", "fr": "Salut", "de": "Hallo"})
    widget.set_value({"en": "Bonjour"})
    assert list(widget._strings.keys()) == ["en"]
    assert widget.get_value() == "Bonjour"


def test_default_locale_can_be_overridden(qtbot):
    """A studio that wants Japanese as the canonical default can pass
    it in — single-ja manifests then collapse to a plain string
    instead of being wrapped in a {ja: ...} dict."""
    w = LocalizedDescriptionInput(default_locale="ja")
    qtbot.addWidget(w)
    w.set_value("only japanese")
    assert w._active == "ja"
    assert w.get_value() == "only japanese"
