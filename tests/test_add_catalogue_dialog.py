"""Smoke tests for the two-step add-catalogue picker.

Replaces the old flat 5-item ``QInputDialog.getItem`` with a scope →
transport split. These tests pin the stack navigation (step1 → step2a
/ step2b, back button returns to step1) and the result codes each
terminal option emits, so a refactor can't silently rewire a button
to the wrong handler.
"""

import pytest

pytest.importorskip("pytestqt")

from carton.ui.compat import QtWidgets
from carton.ui.settings_widgets import _AddCatalogueMethodDialog


@pytest.fixture
def dlg(qtbot):
    d = _AddCatalogueMethodDialog()
    qtbot.addWidget(d)
    return d


def _option_buttons(widget):
    """Collect the big outlined option buttons on a step page.

    The back button is styled via ``btn_ghost_text`` which we filter out
    by its ``←`` arrow prefix — everything else on the page is a
    genuine option choice.
    """
    return [
        b for b in widget.findChildren(QtWidgets.QPushButton)
        if not b.text().startswith("\u2190")
    ]


def test_starts_on_step1(dlg):
    assert dlg._stack.currentIndex() == 0
    # Step 1 exposes exactly two options: single / catalogue.
    buttons = _option_buttons(dlg._stack.currentWidget())
    assert len(buttons) == 2


def test_single_path_shows_two_transports(dlg, qtbot):
    step1_buttons = _option_buttons(dlg._stack.widget(0))
    # First button on step1 is Single package.
    qtbot.mouseClick(step1_buttons[0], pytest.importorskip("PySide6.QtCore").Qt.LeftButton)
    assert dlg._stack.currentIndex() == 1
    assert len(_option_buttons(dlg._stack.currentWidget())) == 2


def test_catalogue_path_shows_three_transports(dlg, qtbot):
    from PySide6.QtCore import Qt

    step1_buttons = _option_buttons(dlg._stack.widget(0))
    qtbot.mouseClick(step1_buttons[1], Qt.LeftButton)
    assert dlg._stack.currentIndex() == 2
    assert len(_option_buttons(dlg._stack.currentWidget())) == 3


def test_back_button_returns_to_step1(dlg, qtbot):
    from PySide6.QtCore import Qt

    # Navigate to step2a.
    qtbot.mouseClick(_option_buttons(dlg._stack.widget(0))[0], Qt.LeftButton)
    assert dlg._stack.currentIndex() == 1

    # The back button on step2a is the only button prefixed with ←.
    back = [b for b in dlg._stack.widget(1).findChildren(QtWidgets.QPushButton)
            if b.text().startswith("\u2190")][0]
    qtbot.mouseClick(back, Qt.LeftButton)
    assert dlg._stack.currentIndex() == 0


def test_terminal_options_set_expected_result_codes(dlg):
    """Drive the dialog by calling _finish directly to avoid exec_."""
    for code in (
        _AddCatalogueMethodDialog.GITHUB,
        _AddCatalogueMethodDialog.PACKAGE_URL,
        _AddCatalogueMethodDialog.REMOTE,
        _AddCatalogueMethodDialog.LOCAL,
        _AddCatalogueMethodDialog.CREATE_NEW,
    ):
        d = _AddCatalogueMethodDialog()
        d._finish(code)
        assert d.result_method() == code


def test_default_result_is_cancel(dlg):
    assert dlg.result_method() == _AddCatalogueMethodDialog.CANCEL
