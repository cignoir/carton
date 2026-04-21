"""Smoke tests for the Carton main window.

These tests only verify that the window constructs, can accept the
stub service wiring, and exposes the expected top-level widgets. They
are the safety net that lets us refactor main_window.py (task #5)
without silently breaking Qt signal wiring.

Anything deeper (profile flows, install handlers, publish dialog) will
live in its own targeted test module as the controllers get extracted.
"""

import pytest

pytest.importorskip("pytestqt")

from carton.ui.compat import QtWidgets
from carton.ui.main_window import CartonWindow


@pytest.fixture
def window(qtbot):
    """Construct a CartonWindow with no services wired.

    ``set_services`` is intentionally skipped — the widget tree must
    survive construction on its own so tests can exercise it without
    standing up catalogue client / installer / downloader stubs.
    """
    win = CartonWindow()
    qtbot.addWidget(win)
    return win


def test_window_constructs(window):
    assert window.windowTitle().startswith("Carton")


def test_core_widgets_present(window):
    """The sidebar lists and the stacked pages must exist after init.

    If a refactor removes one of these attributes the follow-up
    controller extraction will need to re-expose them, so pinning
    them here catches accidental attribute loss early.
    """
    assert isinstance(window._profile_combo, QtWidgets.QComboBox)
    assert isinstance(window._catalogue_list, QtWidgets.QListWidget)
    assert isinstance(window._mytools_list, QtWidgets.QListWidget)
    assert window._stack.count() >= 2  # list page + detail page


def test_set_services_accepts_none_config(window):
    """set_services tolerates a partially-wired service bundle.

    Maya boot paths call set_services incrementally while the UI is
    visible; _rebuild_profile_combo must short-circuit when config is
    still absent instead of raising.
    """
    window.set_services(
        catalogue_client=None,
        install_manager=None,
        downloader=None,
        config=None,
    )
    assert window._config is None
