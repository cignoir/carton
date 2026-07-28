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
import threading
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
        self.artifact_calls = []

    def download(self, url, dest, expected_sha256=None, expected_size=None):
        self.calls.append((url, dest, expected_sha256, expected_size))
        with open(dest, "wb") as f:
            f.write(b"fake-zip-bytes")

    def download_artifact(self, artifact_ref, dest, cache=None):
        self.artifact_calls.append((artifact_ref, dest, cache))
        with open(dest, "wb") as f:
            f.write(b"fake-zip-bytes")
        return dest


class _StubInstallManager:
    def __init__(self):
        self.installed = []

    def install_package(self, zip_path, meta):
        self.installed.append((zip_path, dict(meta)))


class _StubWindow(QtWidgets.QWidget):
    """Stand-in for CartonWindow.

    Really is a QWidget: the controller passes the window as the parent
    of the busy dialog that fronts the download, so a plain object would
    only fail at click time — the exact class of breakage this module
    exists to catch.
    """

    def __init__(self, staging_dir, packages, origin=None):
        super().__init__()
        self._downloader = _StubDownloader()
        self._install_manager = _StubInstallManager()
        self._catalogue_client = types.SimpleNamespace(
            get_packages=lambda: packages,
            get_origin=lambda pkg_id: origin,
            source_cache="stub-cache",
        )
        # The controller reads every path off the window's config — the
        # same Config instance the services were built from.
        self._config = types.SimpleNamespace(
            strict_verify=False, icon_cache_dir="",
            staging_dir=staging_dir,
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


def test_install_uses_origin_artifact_path_with_cache(qtbot, tmp_path, errors):
    """Packages backed by an Origin download via download_artifact so the
    shared SourceCache applies TOFU pinning — the legacy download() path
    is only for origin-less projections."""
    staging = tmp_path / "staging"
    staging.mkdir()
    ref = types.SimpleNamespace(url="https://example.invalid/z.zip",
                                sha256="0" * 64, size_bytes=None,
                                is_pinned=True, source_label="stub")
    origin = types.SimpleNamespace(get_artifact=lambda version: ref)
    w = _StubWindow(str(staging), {PKG_ID: _pkg_data()}, origin=origin)

    InstallController(w).install(PKG_ID)

    assert errors == []
    assert len(w._downloader.artifact_calls) == 1
    got_ref, _dest, cache = w._downloader.artifact_calls[0]
    assert got_ref is ref
    assert cache == "stub-cache"
    # Legacy download() must not have run.
    assert w._downloader.calls == []
    assert len(w._install_manager.installed) == 1


def test_install_unknown_package_is_a_noop(qtbot, tmp_path, errors):
    staging = tmp_path / "staging"
    staging.mkdir()
    w = _StubWindow(str(staging), {})

    InstallController(w).install("nope/missing")

    assert errors == []
    assert w._downloader.calls == []
    assert w._install_manager.installed == []


def test_download_runs_off_the_ui_thread(qtbot, tmp_path, errors):
    """The network half must not execute on the thread painting Maya.

    Between the origin lookup and the downloader's retry loop this is
    minutes of blocking I/O against a host that may be unreachable.
    Asserting on the thread identity is the only way to keep it there —
    a regression would be invisible until someone's VPN dropped.
    """
    staging = tmp_path / "staging"
    staging.mkdir()
    w = _StubWindow(str(staging), {PKG_ID: _pkg_data()})

    seen = {}
    real_download = w._downloader.download

    def _recording_download(url, dest, expected_sha256=None, expected_size=None):
        seen["thread"] = threading.get_ident()
        return real_download(url, dest, expected_sha256=expected_sha256,
                             expected_size=expected_size)

    w._downloader.download = _recording_download

    InstallController(w).install(PKG_ID)

    assert errors == []
    assert seen["thread"] != threading.get_ident()


def test_install_runs_on_the_ui_thread(qtbot, tmp_path, errors):
    """...and the install half must stay on it.

    Handlers call maya.cmds / maya.mel, which are main-thread only, so
    install_package() must never be swept into the worker along with the
    download.
    """
    staging = tmp_path / "staging"
    staging.mkdir()
    w = _StubWindow(str(staging), {PKG_ID: _pkg_data()})

    seen = {}
    real_install = w._install_manager.install_package

    def _recording_install(zip_path, meta):
        seen["thread"] = threading.get_ident()
        return real_install(zip_path, meta)

    w._install_manager.install_package = _recording_install

    InstallController(w).install(PKG_ID)

    assert errors == []
    assert seen["thread"] == threading.get_ident()


def test_failed_install_does_not_leave_the_zip_in_staging(
        qtbot, tmp_path, errors):
    """A failed install used to leak its download into .staging forever."""
    staging = tmp_path / "staging"
    staging.mkdir()
    w = _StubWindow(str(staging), {PKG_ID: _pkg_data()})

    def _boom(zip_path, meta):
        raise RuntimeError("handler exploded")

    w._install_manager.install_package = _boom

    InstallController(w).install(PKG_ID)

    assert len(errors) == 1
    assert list(staging.iterdir()) == []
