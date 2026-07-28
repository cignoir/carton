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


class TestBootstrapDiscardsUnusablePending:
    """A damaged pending_update.json must not be able to block startup.

    ``_apply_pending_update`` runs before ``carton.startup()``, so an
    exception escaping it means Carton does not load. Leaving the file
    on disk would make that permanent: every subsequent Maya launch
    would re-read the same damaged record and fail the same way, with no
    in-product way out.
    """

    def _install_marker(self, tmp_path):
        carton_dir = tmp_path / "carton"
        carton_dir.mkdir()
        (carton_dir / "__init__.py").write_text("OLD", encoding="utf-8")

    def test_truncated_json_is_discarded(self, tmp_path):
        bootstrap = _load_bootstrap()
        self._install_marker(tmp_path)
        # Exactly what an interrupted stage_update used to leave behind.
        (tmp_path / "pending_update.json").write_text(
            '{\n  "package": "carton",\n  "vers', encoding="utf-8")

        bootstrap._apply_pending_update(str(tmp_path))

        assert not (tmp_path / "pending_update.json").exists()
        assert (tmp_path / "carton" / "__init__.py").read_text(
            encoding="utf-8") == "OLD"

    def test_missing_staged_zip_key_is_discarded(self, tmp_path):
        bootstrap = _load_bootstrap()
        self._install_marker(tmp_path)
        (tmp_path / "pending_update.json").write_text(
            json.dumps({"package": "carton", "version": "9.9.9"}),
            encoding="utf-8")

        bootstrap._apply_pending_update(str(tmp_path))

        assert not (tmp_path / "pending_update.json").exists()

    def test_non_object_json_is_discarded(self, tmp_path):
        bootstrap = _load_bootstrap()
        self._install_marker(tmp_path)
        (tmp_path / "pending_update.json").write_text("[]", encoding="utf-8")

        bootstrap._apply_pending_update(str(tmp_path))

        assert not (tmp_path / "pending_update.json").exists()

    def test_pending_without_version_still_applies(self, tmp_path):
        """A missing display-only field must not trigger a rollback."""
        bootstrap = _load_bootstrap()
        carton_dir = tmp_path / "carton"
        carton_dir.mkdir()
        (carton_dir / "__init__.py").write_text("OLD", encoding="utf-8")
        staging = tmp_path / ".staging"
        staging.mkdir()
        (staging / "carton-9.9.9.zip").write_bytes(_zip_bytes())
        (tmp_path / "pending_update.json").write_text(json.dumps({
            "package": "carton",
            "staged_zip": os.path.join(".staging", "carton-9.9.9.zip"),
        }), encoding="utf-8")

        bootstrap._apply_pending_update(str(tmp_path))

        assert (tmp_path / "carton" / "__init__.py").read_text(
            encoding="utf-8") == "NEW"

    def test_start_survives_an_exploding_update(self, tmp_path, monkeypatch):
        """``start()`` must reach ``carton.startup()`` regardless."""
        bootstrap = _load_bootstrap()
        monkeypatch.setattr(bootstrap, "_find_bootstrap_dir",
                            lambda: str(tmp_path))

        def _boom(_dir):
            raise OSError("disk on fire")

        monkeypatch.setattr(bootstrap, "_apply_pending_update", _boom)

        started = []
        fake_carton = types.ModuleType("carton")
        fake_carton.startup = lambda: started.append(True)
        monkeypatch.setitem(__import__("sys").modules, "carton", fake_carton)

        bootstrap.start()

        assert started == [True]


class TestStagedRecordIsAtomic:
    def test_pending_update_written_via_temp_file(self, monkeypatch, tmp_path):
        """The staged record must never be observable half-written.

        A truncated pending_update.json is read by the bootstrap before
        anything else at Maya startup, so the write has to be a single
        filesystem operation.
        """
        monkeypatch.setattr(su_module, "default_bootstrap_dir",
                            lambda: str(tmp_path))
        updater, _ = _make_updater(monkeypatch, _release_payload())

        seen = []
        real_replace = su_module.write_json_atomic

        def _spy(path, data, **kwargs):
            seen.append(path)
            return real_replace(path, data, **kwargs)

        monkeypatch.setattr(su_module, "write_json_atomic", _spy)
        updater.stage_update("9.9.9", "https://example.invalid/z.zip", ZIP_SHA)

        assert seen == [str(tmp_path / "pending_update.json")]
        # No temp file left behind after a successful write.
        assert not (tmp_path / "pending_update.json.tmp").exists()

    def test_get_pending_version_tolerates_damage(self, monkeypatch, tmp_path):
        monkeypatch.setattr(su_module, "default_bootstrap_dir",
                            lambda: str(tmp_path))
        updater, _ = _make_updater(monkeypatch, _release_payload())
        (tmp_path / "pending_update.json").write_text("{oh no",
                                                      encoding="utf-8")

        assert updater.get_pending_version() is None


class TestShippedBootstrapIsTheTestedBootstrap:
    """The installer must deploy the file this module exercises.

    These two used to be separate hand-maintained copies, and the one
    users actually ran was the copy without staged-update sha256
    verification. Everything above this line tests ``bootstrap/`` — this
    test is what makes those assertions mean something in production.
    """

    def _build_installer(self, tmp_path, monkeypatch):
        builder_path = os.path.join(os.path.dirname(__file__), os.pardir,
                                    "scripts", "build_installer.py")
        spec = importlib.util.spec_from_file_location(
            "_carton_build_installer_bs", os.path.abspath(builder_path))
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        monkeypatch.setattr(builder, "DIST_DIR", str(tmp_path))
        out_path = tmp_path / "installer.py"
        builder.build(version="9.9.9", profile_path=None, output=str(out_path))
        gen_spec = importlib.util.spec_from_file_location(
            "_gen_installer_bs", str(out_path))
        gen = importlib.util.module_from_spec(gen_spec)
        gen_spec.loader.exec_module(gen)
        return gen

    def test_generated_installer_embeds_the_repo_bootstrap(
            self, tmp_path, monkeypatch):
        gen = self._build_installer(tmp_path, monkeypatch)
        repo_bootstrap = os.path.join(
            os.path.dirname(__file__), os.pardir, "bootstrap",
            "carton_bootstrap.py")
        with open(os.path.abspath(repo_bootstrap), "r", encoding="utf-8") as f:
            expected = f.read()

        assert gen.BOOTSTRAP_PY == expected

    def test_shipped_bootstrap_verifies_the_staged_zip(
            self, tmp_path, monkeypatch):
        """Guard the specific protection that silently went missing."""
        gen = self._build_installer(tmp_path, monkeypatch)

        assert "_sha256_of" in gen.BOOTSTRAP_PY
        assert "sha256 mismatch" in gen.BOOTSTRAP_PY

    def test_generated_installer_embeds_the_repo_usersetup_hook(
            self, tmp_path, monkeypatch):
        gen = self._build_installer(tmp_path, monkeypatch)
        repo_hook = os.path.join(os.path.dirname(__file__), os.pardir,
                                 "bootstrap", "userSetup.py")
        with open(os.path.abspath(repo_hook), "r", encoding="utf-8") as f:
            expected = f.read()

        # Leading newline separates the hook from any pre-existing
        # userSetup.py content the installer appends to.
        assert gen.USERSETUP_HOOK == "\n" + expected
        assert "carton_bootstrap" in gen.USERSETUP_HOOK
