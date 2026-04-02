"""Tests for Config."""

import json
import os
import tempfile

from carton.core.config import Config, RegistryEntry


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
            assert loaded.registries[0].path == "/some/path/registry.json"

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


class TestRegistryEntry:
    def test_base_dir(self):
        e = RegistryEntry("test", "/some/dir/registry.json")
        assert e.base_dir == os.path.normpath("/some/dir")

    def test_to_dict(self):
        e = RegistryEntry("test", "/path/registry.json")
        d = e.to_dict()
        assert d["name"] == "test"
        assert d["path"] == "/path/registry.json"
