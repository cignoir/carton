"""Refresh must not block the thread that paints Maya.

``CartonWindow.refresh()`` issues one HTTP round trip per subscribed
remote catalogue, in series, each with its own timeout. Run inline it
freezes all of Maya for as long as the slowest unreachable host takes to
give up — and it fires on window open, on the toolbar button, and every
time the settings dialog closes.
"""

import threading
import types

import pytest

pytest.importorskip("pytestqt")

import carton.ui.main_window as mw_module
from carton.ui.main_window import CartonWindow


class _StubCatalogueClient:
    def __init__(self, on_fetch=None):
        self.fetch_calls = 0
        self.fetch_threads = []
        self._on_fetch = on_fetch

    def fetch(self):
        self.fetch_calls += 1
        self.fetch_threads.append(threading.get_ident())
        if self._on_fetch:
            self._on_fetch()

    def get_packages(self):
        return {}

    def get_origin(self, pkg_id):
        return None


def _window(qtbot, client):
    win = CartonWindow()
    qtbot.addWidget(win)
    win._catalogue_client = client
    win._install_manager = types.SimpleNamespace(
        get_installed_packages=lambda: {},
    )
    # Self-update check and publish badges are separate flows; stub them
    # out so this module only exercises the fetch.
    win._check_self_update = lambda force=False: None
    win._build_published_map = lambda: {}
    return win


def test_fetch_runs_off_the_ui_thread(qtbot):
    client = _StubCatalogueClient()
    win = _window(qtbot, client)

    win.refresh()

    assert client.fetch_calls == 1
    assert client.fetch_threads[0] != threading.get_ident()


def test_views_rebuild_after_the_fetch_completes(qtbot):
    """refresh() still reads synchronously — callers depend on that."""
    client = _StubCatalogueClient()
    win = _window(qtbot, client)
    order = []
    win._rebuild_sidebar = lambda: order.append("sidebar")
    win._rebuild_cards = lambda: order.append("cards")

    win.refresh()

    assert order == ["sidebar", "cards"]
    assert client.fetch_calls == 1


def test_cards_are_built_once_per_refresh(qtbot):
    """The sidebar's selection signal already rebuilds the cards.

    Doing it again unconditionally meant every card widget was
    constructed twice per refresh, and the second pass had to stop and
    join the icon fetcher the first one had just started.
    """
    client = _StubCatalogueClient()
    win = _window(qtbot, client)
    rebuilds = []
    win._rebuild_cards = lambda: rebuilds.append(True)

    win.refresh()
    assert len(rebuilds) == 1

    # Second refresh restores the same selection, so no signal fires and
    # refresh() has to do the rebuild itself.
    rebuilds.clear()
    win.refresh()
    assert len(rebuilds) == 1


def test_reentrant_refresh_is_dropped(qtbot):
    """A refresh triggered from inside a refresh must not stack.

    The worker runs a nested event loop, so queued events — a second
    click on the toolbar button, a settings dialog closing — get
    delivered while the first fetch is still in flight.
    """
    client = _StubCatalogueClient()
    win = _window(qtbot, client)

    def _reenter():
        win.refresh()

    client._on_fetch = _reenter

    win.refresh()

    assert client.fetch_calls == 1


def test_fetch_failure_surfaces_and_still_rebuilds(qtbot, monkeypatch):
    """A broken fetch must not leave the user on a blank window."""
    shown = []
    monkeypatch.setattr(
        mw_module, "show_error",
        lambda parent, exc, operation=None: shown.append((exc, operation)),
    )

    def _boom():
        raise RuntimeError("catalogue subsystem died")

    client = _StubCatalogueClient(on_fetch=_boom)
    win = _window(qtbot, client)
    rebuilt = []
    win._rebuild_cards = lambda: rebuilt.append(True)

    win.refresh()

    assert len(shown) == 1
    assert shown[0][1] == "refresh"
    assert rebuilt
    # The guard must be released even on the failure path, or refresh()
    # would be dead for the rest of the session.
    assert win._refreshing is False


def test_refresh_without_a_client_is_a_noop(qtbot):
    win = CartonWindow()
    qtbot.addWidget(win)
    win.refresh()  # must not raise
