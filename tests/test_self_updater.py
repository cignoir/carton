"""Tests for SelfUpdater and the bootstrap's staged-update verification.

This path replaces the carton/ package itself at Maya startup, so it is
held to the same integrity bar as package installs: the release asset's
sha256 digest is verified at download time, recorded in
pending_update.json, and re-verified by the bootstrap right before
extraction.
"""

import importlib.util
import io
import json
import hashlib
import os
import types
import zipfile

import pytest

import carton
import carton.core.self_updater as su_module
from carton.core.downloader import DownloadError
from carton.core.self_updater import SelfUpdater, _asset_sha256


ZIP_SHA = "a" * 64


def _release_payload(tag="v9.9.9", digest="sha256:" + ZIP_SHA):
    asset = {
        "name": "carton-v9.9.9.zip",
        "browser_download_url": "https://example.invalid/carton-v9.9.9.zip",
    }
    if digest is not None:
        asset["digest"] = digest
    return {"tag_name": tag, "assets": [
        {"name": "install_carton.py", "browser_download_url": "x"},
        asset,
    ]}


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body


class _StubDownloader:
    def __init__(self):
        self.calls = []

    def download(self, url, dest, expected_sha256=None, expected_size=None):
        self.calls.append((url, dest, expected_sha256))
        with open(dest, "wb") as f:
            f.write(b"zip-bytes")


def _make_updater(monkeypatch, payload, strict=False):
    config = types.SimpleNamespace(github_repo="acme/carton",
                                   strict_verify=strict)
    downloader = _StubDownloader()
    updater = SelfUpdater(config, downloader)
    monkeypatch.setattr(su_module, "urlopen",
                        lambda req, timeout=10: _FakeResponse(payload))
    monkeypatch.setattr(carton, "__version__", "1.0.0")
    return updater, downloader


class TestCheckUpdate:
    def test_newer_release_returns_url_and_sha(self, monkeypatch):
        updater, _ = _make_updater(monkeypatch, _release_payload())
        assert updater.check_update() == (
            "9.9.9", "https://example.invalid/carton-v9.9.9.zip", ZIP_SHA,
        )

    def test_missing_digest_returns_none_sha(self, monkeypatch):
        updater, _ = _make_updater(monkeypatch,
                                   _release_payload(digest=None))
        result = updater.check_update()
        assert result is not None
        assert result[2] is None

    def test_same_version_returns_none(self, monkeypatch):
        updater, _ = _make_updater(monkeypatch,
                                   _release_payload(tag="v1.0.0"))
        assert updater.check_update() is None

    def test_no_zip_asset_returns_none(self, monkeypatch):
        payload = {"tag_name": "v9.9.9", "assets": []}
        updater, _ = _make_updater(monkeypatch, payload)
        assert updater.check_update() is None

    def test_network_error_returns_none(self, monkeypatch):
        updater, _ = _make_updater(monkeypatch, {})

        def _boom(req, timeout=10):
            raise OSError("no network")

        monkeypatch.setattr(su_module, "urlopen", _boom)
        assert updater.check_update() is None


class TestStageUpdate:
    @pytest.fixture
    def bootstrap_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(su_module, "default_bootstrap_dir",
                            lambda: str(tmp_path))
        return tmp_path

    def test_passes_sha_to_downloader_and_records_it(
            self, monkeypatch, bootstrap_dir):
        updater, downloader = _make_updater(monkeypatch, _release_payload())

        updater.stage_update("9.9.9", "https://example.invalid/z.zip",
                             ZIP_SHA)

        assert downloader.calls[0][2] == ZIP_SHA
        pending = json.loads(
            (bootstrap_dir / "pending_update.json").read_text("utf-8"))
        assert pending["sha256"] == ZIP_SHA
        assert pending["version"] == "9.9.9"

    def test_no_sha_stages_without_pin(self, monkeypatch, bootstrap_dir):
        updater, downloader = _make_updater(monkeypatch, _release_payload())

        updater.stage_update("9.9.9", "https://example.invalid/z.zip")

        assert downloader.calls[0][2] is None
        pending = json.loads(
            (bootstrap_dir / "pending_update.json").read_text("utf-8"))
        assert "sha256" not in pending

    def test_strict_verify_refuses_unverifiable_update(
            self, monkeypatch, bootstrap_dir):
        updater, downloader = _make_updater(monkeypatch, _release_payload(),
                                            strict=True)

        with pytest.raises(DownloadError):
            updater.stage_update("9.9.9", "https://example.invalid/z.zip")

        assert downloader.calls == []
        assert not (bootstrap_dir / "pending_update.json").exists()


def test_asset_sha256_parsing():
    assert _asset_sha256({"digest": "sha256:" + ZIP_SHA}) == ZIP_SHA
    assert _asset_sha256({"digest": "sha512:beef"}) is None
    assert _asset_sha256({"digest": ""}) is None
    assert _asset_sha256({}) is None


# ---------- bootstrap-side verification ------------------------------------


def _load_bootstrap():
    path = os.path.join(os.path.dirname(__file__), os.pardir,
                        "bootstrap", "carton_bootstrap.py")
    spec = importlib.util.spec_from_file_location("carton_bootstrap_ut",
                                                  os.path.abspath(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stage(tmp_path, sha_in_pending):
    """Lay out bootstrap_dir with an installed carton/ and a staged zip."""
    carton_dir = tmp_path / "carton"
    carton_dir.mkdir()
    (carton_dir / "__init__.py").write_text("OLD", encoding="utf-8")

    staging = tmp_path / ".staging"
    staging.mkdir()
    zip_path = staging / "carton-9.9.9.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("carton/__init__.py", "NEW")
    zip_path.write_bytes(buf.getvalue())

    pending = {
        "package": "carton",
        "version": "9.9.9",
        "staged_zip": os.path.join(".staging", "carton-9.9.9.zip"),
    }
    if sha_in_pending is not None:
        pending["sha256"] = sha_in_pending
    (tmp_path / "pending_update.json").write_text(
        json.dumps(pending), encoding="utf-8")
    return zip_path


class TestBootstrapApply:
    def test_matching_sha_applies_update(self, tmp_path):
        bootstrap = _load_bootstrap()
        zip_path = _stage(tmp_path,
                          hashlib.sha256(_zip_bytes()).hexdigest())

        bootstrap._apply_pending_update(str(tmp_path))

        assert (tmp_path / "carton" / "__init__.py").read_text(
            encoding="utf-8") == "NEW"
        assert not (tmp_path / "pending_update.json").exists()
        assert not zip_path.exists()

    def test_mismatching_sha_discards_update(self, tmp_path):
        bootstrap = _load_bootstrap()
        zip_path = _stage(tmp_path, "0" * 64)

        bootstrap._apply_pending_update(str(tmp_path))

        # Current install untouched, poisoned staging cleaned up.
        assert (tmp_path / "carton" / "__init__.py").read_text(
            encoding="utf-8") == "OLD"
        assert not (tmp_path / "pending_update.json").exists()
        assert not zip_path.exists()

    def test_legacy_pending_without_sha_still_applies(self, tmp_path):
        bootstrap = _load_bootstrap()
        _stage(tmp_path, None)

        bootstrap._apply_pending_update(str(tmp_path))

        assert (tmp_path / "carton" / "__init__.py").read_text(
            encoding="utf-8") == "NEW"


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("carton/__init__.py", "NEW")
    return buf.getvalue()
