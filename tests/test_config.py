"""Tests for Config."""

import json
import os
import tempfile

import pytest

from carton.core.config import Config, InstallDirChangeError, RegistryEntry


class TestConfig:
    def test_defaults(self):
        c = Config()
        assert c.registries == []
        assert c.auto_check_updates is True
        assert c.github_repo == "cignoir/carton"

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            c = Config()
            c.add_registry("test", "/some/path/registry.json")
            c.save(path)

            loaded = Config.load(path)
            assert len(loaded.registries) == 1
            assert loaded.registries[0].name == "test"
            assert loaded.registries[0].path == os.path.normpath("/some/path/registry.json")

    def test_load_missing(self):
        c = Config.load("/nonexistent/path/config.json")
        assert c.registries == []

    def test_properties(self):
        c = Config(install_dir="/tmp/carton")
        assert c.packages_dir == os.path.join("/tmp/carton", "packages")
        assert c.staging_dir == os.path.join("/tmp/carton", ".staging")

    def test_add_remove_registry(self):
        c = Config()
        c.add_registry("a", "/path/a.json")
        c.add_registry("b", "/path/b.json")
        assert len(c.registries) == 2

        c.remove_registry("a")
        assert len(c.registries) == 1
        assert c.registries[0].name == "b"


class TestChangeInstallDir:
    def _seed(self, install_dir):
        """Populate install_dir with the files change_install_dir should move."""
        os.makedirs(os.path.join(install_dir, "packages", "ns", "pkg"))
        with open(os.path.join(install_dir, "packages", "ns", "pkg", "marker.txt"), "w") as f:
            f.write("hello")
        with open(os.path.join(install_dir, "installed.json"), "w") as f:
            f.write('{"schema_version": "3.0", "packages": {}}')
        os.makedirs(os.path.join(install_dir, ".staging"))
        os.makedirs(os.path.join(install_dir, ".icon_cache"))

    def test_move_to_new_empty_dir(self, tmp_path, monkeypatch):
        old = tmp_path / "old"
        new = tmp_path / "new"
        old.mkdir()
        self._seed(str(old))

        # Redirect config.json to a tmp location so save() doesn't touch
        # the user's real home during tests.
        config_path = tmp_path / "config.json"
        monkeypatch.setattr(
            "carton.core.config.default_config_path",
            lambda: str(config_path),
        )

        c = Config(install_dir=str(old))
        c.change_install_dir(str(new))

        assert c.install_dir == os.path.abspath(str(new))
        assert (new / "packages" / "ns" / "pkg" / "marker.txt").exists()
        assert (new / "installed.json").exists()
        assert not (old / "packages").exists()
        assert not (old / "installed.json").exists()
        # config.json was persisted to the canonical bootstrap path
        assert config_path.exists()
        with open(config_path) as f:
            data = json.load(f)
        assert data["install_dir"] == os.path.abspath(str(new))

    def test_refuses_non_empty_destination(self, tmp_path, monkeypatch):
        old = tmp_path / "old"
        new = tmp_path / "new"
        old.mkdir()
        new.mkdir()
        (new / "something.txt").write_text("existing content")
        self._seed(str(old))

        monkeypatch.setattr(
            "carton.core.config.default_config_path",
            lambda: str(tmp_path / "config.json"),
        )
        c = Config(install_dir=str(old))
        with pytest.raises(InstallDirChangeError, match="not empty"):
            c.change_install_dir(str(new))
        # Old location is untouched
        assert (old / "packages" / "ns" / "pkg" / "marker.txt").exists()

    def test_refuses_nesting(self, tmp_path, monkeypatch):
        old = tmp_path / "old"
        old.mkdir()
        self._seed(str(old))
        nested = old / "inside"
        monkeypatch.setattr(
            "carton.core.config.default_config_path",
            lambda: str(tmp_path / "config.json"),
        )
        c = Config(install_dir=str(old))
        with pytest.raises(InstallDirChangeError, match="inside"):
            c.change_install_dir(str(nested))

    def test_same_dir_is_noop(self, tmp_path, monkeypatch):
        old = tmp_path / "old"
        old.mkdir()
        self._seed(str(old))
        monkeypatch.setattr(
            "carton.core.config.default_config_path",
            lambda: str(tmp_path / "config.json"),
        )
        c = Config(install_dir=str(old))
        c.change_install_dir(str(old))  # Should silently return
        assert c.install_dir == str(old)
        assert (old / "installed.json").exists()


class TestProxy:
    def test_apply_proxy_sets_env_vars(self, monkeypatch):
        # Clear any ambient proxy values so the assertion is deterministic.
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            monkeypatch.delenv(k, raising=False)
        c = Config(proxy="http://proxy.example.com:8080")
        c.apply_proxy_to_env()
        assert os.environ["HTTP_PROXY"] == "http://proxy.example.com:8080"
        assert os.environ["HTTPS_PROXY"] == "http://proxy.example.com:8080"
        assert os.environ["http_proxy"] == "http://proxy.example.com:8080"

    def test_empty_proxy_leaves_env_untouched(self, monkeypatch):
        monkeypatch.setenv("HTTP_PROXY", "http://ambient:3128")
        c = Config(proxy="")
        c.apply_proxy_to_env()
        assert os.environ["HTTP_PROXY"] == "http://ambient:3128"

    def test_proxy_round_trips_through_save_load(self, tmp_path):
        path = tmp_path / "config.json"
        c = Config(proxy="http://p:1234")
        c.save(str(path))
        loaded = Config.load(str(path))
        assert loaded.proxy == "http://p:1234"


class TestRegistryEntry:
    def test_base_dir(self):
        e = RegistryEntry("test", "/some/dir/registry.json")
        assert e.base_dir == os.path.normpath("/some/dir")

    def test_to_dict(self):
        e = RegistryEntry("test", "/path/registry.json")
        d = e.to_dict()
        assert d["name"] == "test"
        assert d["path"] == os.path.normpath("/path/registry.json")
