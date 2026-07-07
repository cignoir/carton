"""Regression tests for the Settings "Check for updates now" button.

The button builds its worker via an import resolved only at click time,
so a refactor that moves or renames the worker class breaks the feature
without any test noticing (regression: ``_SelfUpdateCheckWorker`` stayed
pointing at ``main_window`` after the class moved to
``_self_update_controller`` as ``SelfUpdateCheckWorker``). These tests
click through the flow with a stub updater so the wiring is exercised
in CI.
"""

import types

import pytest

pytest.importorskip("pytestqt")

import carton.ui.settings_widgets as sw_module
from carton.ui.settings_widgets import AutoUpdateSection


class _StubSelfUpdater:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls = 0

    def check_update(self):
        self.calls += 1
        if self._error is not None:
            raise RuntimeError(self._error)
        return self._result


@pytest.fixture
def message_boxes(monkeypatch):
    """Capture QMessageBox calls instead of opening modal dialogs."""
    captured = {"information": [], "warning": []}
    monkeypatch.setattr(
        sw_module.QtWidgets.QMessageBox, "information",
        staticmethod(lambda *a, **k: captured["information"].append(a)),
    )
    monkeypatch.setattr(
        sw_module.QtWidgets.QMessageBox, "warning",
        staticmethod(lambda *a, **k: captured["warning"].append(a)),
    )
    return captured


def _make_section(qtbot, updater):
    target = types.SimpleNamespace(auto_check_updates=True)
    section = AutoUpdateSection(target, persist=lambda: None,
                                self_updater=updater)
    qtbot.addWidget(section)
    return section


def _click_and_wait(qtbot, section):
    section._on_check_now()
    # The worker re-enables the button from its finished signal; waiting
    # on that state proves the full click -> worker -> done round trip.
    qtbot.waitUntil(lambda: section._check_btn.isEnabled(), timeout=5000)
    if section._update_worker is not None:
        section._update_worker.wait(5000)


def test_check_now_up_to_date(qtbot, message_boxes):
    updater = _StubSelfUpdater(result=None)
    section = _make_section(qtbot, updater)

    _click_and_wait(qtbot, section)

    assert updater.calls == 1
    assert len(message_boxes["information"]) == 1
    assert message_boxes["warning"] == []


def test_check_now_update_available(qtbot, message_boxes):
    updater = _StubSelfUpdater(result=("9.9.9", "https://example.invalid/z"))
    section = _make_section(qtbot, updater)

    _click_and_wait(qtbot, section)

    assert len(message_boxes["information"]) == 1
    # The dialog text carries the offered version.
    assert any("9.9.9" in str(arg)
               for arg in message_boxes["information"][0])


def test_check_now_error_shows_warning(qtbot, message_boxes):
    updater = _StubSelfUpdater(error="network down")
    section = _make_section(qtbot, updater)

    _click_and_wait(qtbot, section)

    assert len(message_boxes["warning"]) == 1
    assert message_boxes["information"] == []
