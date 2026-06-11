"""Targeted tests for the InstallController install flow.

The controller reads services off the window by attribute, so a rename
on either side (window method extracted to a module function, service
attribute renamed) fails only at click time — inside a broad
``except Exception`` that turns it into a generic install-error dialog.
These tests drive ``install()`` against stub services so that wiring
breakage fails in CI instead. Regression guard for the
``w._resolve_icon_path`` -> ``_icon_fetch.resolve_icon_path`` rename.
"""

import os
import types

import pytest

pytest.importorskip("pytestqt")

from carton.ui.compat import QtWidgets
import carton.ui._install_controller as ic_module
from carton.ui._install_controller import InstallController


PKG_ID = "acme/coolrig"


def _pkg_data(with_sha=True):
    version_info = {"download_url": "https://example.invalid/coolrig-1.2.0.zip"}
    if with_sha:
        version_info["sha256"] = "0" * 64
    return {
        "namespace": "acme",
        "name": "coolrig",
        "display_name": "Cool Rig",
        "type": "python_package",
        "latest_version": "1.2.0",
        "versions": {"1.2.0": version_info},
    }


class _StubDownloader:
    def __init__(self):
        self.calls = []

    def download(self, url, dest, expected_sha256=None, expected_size=None):
        self.calls.append((url, dest, expected_sha256, expected_size))
        with open(dest, "wb") as f:
            f.write(b"fake-zip-bytes")


class _StubInstallManager:
    def __init__(self, staging_dir):
        self._config = types.SimpleNamespace(staging_dir=staging_dir)
        self.installed = []

    def install_package(self, zip_path, meta):
        self.installed.append((zip_path, dict(meta)))


class _StubWindow:
    def __init__(self, staging_dir, packages):
        self._downloader = _StubDownloader()
        self._install_manager = _StubInstallManager(staging_dir)
        self._catalogue_client = types.SimpleNamespace(
            get_packages=lambda: packages,
        )
        self._config = types.SimpleNamespace(
            strict_verify=False, icon_cache_dir="",
        )
        self._card_layout = QtWidgets.QVBoxLayout()
        self.sidebar_rebuilds = 0
        self.card_rebuilds = 0

    def _rebuild_sidebar(self):
        self.sidebar_rebuilds += 1

    def _rebuild_cards(self):
        self.card_rebuilds += 1


@pytest.fixture
def errors(monkeypatch):
    """Capture show_error calls instead of opening a QMessageBox.

    The install flow funnels every failure here, so an empty list is
    the strongest available assertion that the happy path stayed happy.
    """
    captured = []
    monkeypatch.setattr(
        ic_module, "show_error",
        lambda parent, exc, operation=None: captured.append(exc),
    )
    return captured


def test_install_happy_path(qtbot, tmp_path, errors):
    staging = tmp_path / "staging"
    staging.mkdir()
    w = _StubWindow(str(staging), {PKG_ID: _pkg_data()})

    InstallController(w).install(PKG_ID)

    assert errors == []
    assert len(w._install_manager.installed) == 1
    zip_path, meta = w._install_manager.installed[0]
    assert meta["id"] == PKG_ID
    assert meta["namespace"] == "acme"
    assert meta["name"] == "coolrig"
    assert meta["version"] == "1.2.0"
    assert meta["pinned"] is False
    # No icon configured -> resolves to "" but the key must exist for
    # relinked My Tools entries.
    assert meta["icon_resolved"] == ""
    # Staging zip is cleaned up after a successful install.
    assert not os.path.exists(zip_path)
    assert w.sidebar_rebuilds == 1
    assert w.card_rebuilds == 1


def test_install_pinned_specific_version(qtbot, tmp_path, errors):
    staging = tmp_path / "staging"
    staging.mkdir()
    w = _StubWindow(str(staging), {PKG_ID: _pkg_data()})

    InstallController(w).install(PKG_ID, version="1.2.0", pinned=True)

    assert errors == []
    _, meta = w._install_manager.installed[0]
    assert meta["version"] == "1.2.0"
    assert meta["pinned"] is True


def test_install_strict_verify_rejects_missing_sha256(qtbot, tmp_path, errors):
    staging = tmp_path / "staging"
    staging.mkdir()
    w = _StubWindow(str(staging), {PKG_ID: _pkg_data(with_sha=False)})
    w._config.strict_verify = True

    InstallController(w).install(PKG_ID)

    assert len(errors) == 1
    assert w._install_manager.installed == []
    # Nothing should have been downloaded before the strict check.
    assert w._downloader.calls == []


def test_install_unknown_package_is_a_noop(qtbot, tmp_path, errors):
    staging = tmp_path / "staging"
    staging.mkdir()
    w = _StubWindow(str(staging), {})

    InstallController(w).install("nope/missing")

    assert errors == []
    assert w._downloader.calls == []
    assert w._install_manager.installed == []
