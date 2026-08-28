"""The main window must surface a catalogue that failed to load.

Companion to tests/test_catalogue_fetch_errors.py: that one pins the
client recording the failure, this one pins the window putting it on
screen. Between them, a catalogue can no longer go missing in silence.
"""

import threading
import types

import pytest

pytest.importorskip("pytestqt")

from carton.ui.main_window import CartonWindow


class _StubClient:
    def __init__(self, errors=()):
        self._errors = list(errors)

    def fetch(self):
        pass

    def get_packages(self):
        return {}

    def get_origin(self, pkg_id):
        return None

    def get_fetch_errors(self):
        return list(self._errors)


def _window(qtbot, client):
    win = CartonWindow()
    qtbot.addWidget(win)
    win._catalogue_client = client
    win._install_manager = types.SimpleNamespace(
        get_installed_packages=lambda: {},
    )
    win._check_self_update = lambda force=False: None
    win._build_published_map = lambda: {}
    return win


def test_banner_hidden_when_every_catalogue_loads(qtbot):
    win = _window(qtbot, _StubClient())

    win.refresh()

    assert not win._catalogue_error_banner.isVisible()


def test_banner_names_the_failed_catalogue(qtbot):
    win = _window(qtbot, _StubClient([
        {"label": "Maya PCG Catalogue",
         "path": "https://example.invalid/catalogue.json",
         "reason": "timed out"},
    ]))

    win.refresh()

    assert win._catalogue_error_banner.isVisibleTo(win)
    assert "Maya PCG Catalogue" in win._catalogue_error_label.text()
    # The reason is what separates "typo" from "host is down"; it lives
    # in the tooltip because the strip has no room for it.
    assert "timed out" in win._catalogue_error_banner.toolTip()


def test_banner_lists_every_failure(qtbot):
    win = _window(qtbot, _StubClient([
        {"label": "One", "path": "a", "reason": "404"},
        {"label": "Two", "path": "b", "reason": "dns"},
    ]))

    win.refresh()

    text = win._catalogue_error_label.text()
    assert "One" in text and "Two" in text


def test_banner_clears_once_the_catalogue_comes_back(qtbot):
    client = _StubClient([{"label": "Flaky", "path": "u", "reason": "reset"}])
    win = _window(qtbot, client)
    win.refresh()
    assert win._catalogue_error_banner.isVisibleTo(win)

    client._errors = []
    win.refresh()

    assert not win._catalogue_error_banner.isVisible()


def test_client_without_the_accessor_is_tolerated(qtbot):
    """set_services is called with partially wired stubs on Maya boot."""
    class _Old:
        def fetch(self):
            pass

        def get_packages(self):
            return {}

        def get_origin(self, pkg_id):
            return None

    win = _window(qtbot, _Old())

    win.refresh()

    assert not win._catalogue_error_banner.isVisible()
