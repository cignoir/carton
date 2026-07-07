"""Tests for run_with_busy — the off-UI-thread call wrapper."""

import time

import pytest

pytest.importorskip("pytestqt")

from carton.ui._busy import run_with_busy


class _MarkerError(RuntimeError):
    pass


def test_returns_result(qtbot):
    assert run_with_busy(None, lambda: 41 + 1) == 42


def test_reraises_original_exception_type(qtbot):
    with pytest.raises(_MarkerError, match="boom"):
        run_with_busy(None, lambda: (_ for _ in ()).throw(_MarkerError("boom")))


def test_slow_call_still_returns(qtbot):
    def _slow():
        time.sleep(0.05)
        return "done"

    assert run_with_busy(None, _slow, show_after_ms=10) == "done"


def test_result_may_be_none(qtbot):
    assert run_with_busy(None, lambda: None) is None
