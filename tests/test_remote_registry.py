"""Tests for remote (URL-based) registry support."""

import json
import os
import tempfile

from carton.core.config import Config, RegistryEntry, _is_url
from carton.core.publisher import Publisher
from carton.core.registry_client import RegistryClient


class TestIsUrl:
    def test_http(self):
        assert _is_url("http://example.com/registry.json") is True

    def test_https(self):
        assert _is_url("https://example.com/registry.json") is True

    def test_local_path(self):
        assert _is_url("/some/local/path/registry.json") is False

    def test_windows_path(self):
        assert _is_url("C:\\Users\\test\\registry.json") is False

    def test_unc_path(self):
        assert _is_url("//server/share/registry.json") is False


class TestRegistryEntryRemote:
    def test_is_remote_url(self):
        e = RegistryEntry("test", "https://example.com/reg/registry.json")
        assert e.is_remote is True

    def test_is_remote_local(self):
        e = RegistryEntry("test", "/some/path/registry.json")
        assert e.is_remote is False

    def test_url_not_normpathed(self):
        """URLs should not be mangled by os.path.normpath."""
        url = "https://raw.githubusercontent.com/org/repo/main/registry.json"
        e = RegistryEntry("test", url)
        assert e.path == url

    def test_base_dir_url(self):
        e = RegistryEntry("test", "https://example.com/registry/registry.json")
        assert e.base_dir == "https://example.com/registry/"

    def test_base_dir_url_nested(self):
        e = RegistryEntry("test", "https://raw.githubusercontent.com/org/repo/main/registry.json")
        assert e.base_dir == "https://raw.githubusercontent.com/org/repo/main/"

    def test_base_dir_local(self):
        e = RegistryEntry("test", "/some/dir/registry.json")
        assert e.base_dir == os.path.normpath("/some/dir")


class TestPublisherRemoteGuard:
    """Publisher should reject write operations on remote registries."""

    def _make_publisher(self):
        config = Config(install_dir=tempfile.mkdtemp())
        return Publisher(config)

    def test_publish_to_remote_raises(self):
        publisher = self._make_publisher()
        remote_entry = RegistryEntry("remote", "https://example.com/registry.json")
        try:
            publisher.publish({}, remote_entry)
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "remote" in str(e).lower()

    def test_unpublish_from_remote_raises(self):
        publisher = self._make_publisher()
        remote_entry = RegistryEntry("remote", "https://example.com/registry.json")
        try:
            publisher.unpublish("fake-id", remote_entry)
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "remote" in str(e).lower()

    def test_find_published_skips_remote(self):
        """find_published_registries should skip remote registries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            config.add_registry("remote", "https://example.com/registry.json")

            # Also add a local registry that doesn't exist
            config.add_registry("local", os.path.join(tmpdir, "nonexistent.json"))

            publisher = Publisher(config)
            results = publisher.find_published_registries("some-uuid")
            # Both should be skipped (remote skipped, local doesn't exist)
            assert results == []


class TestRegistryClientMerge:
    """Test that _merge_packages resolves URLs correctly for remote registries."""

    def test_relative_url_resolution_remote(self):
        """Relative download_url should be joined with remote base URL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            client = RegistryClient(config)

            entry = RegistryEntry("test", "https://example.com/registry/registry.json")
            data = {
                "packages": {
                    "pkg-1": {
                        "name": "tool",
                        "latest_version": "1.0.0",
                        "versions": {
                            "1.0.0": {
                                "download_url": "packages/pkg-1/1.0.0/tool-1.0.0.package",
                            }
                        }
                    }
                }
            }

            client._merge_packages(entry, data)
            pkg = client._packages["pkg-1"]
            resolved = pkg["versions"]["1.0.0"]["download_url"]
            assert resolved == "https://example.com/registry/packages/pkg-1/1.0.0/tool-1.0.0.package"

    def test_absolute_url_not_modified(self):
        """Absolute download_url should not be modified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            client = RegistryClient(config)

            entry = RegistryEntry("test", "https://example.com/registry.json")
            abs_url = "https://cdn.example.com/packages/tool-1.0.0.package"
            data = {
                "packages": {
                    "pkg-1": {
                        "name": "tool",
                        "latest_version": "1.0.0",
                        "versions": {
                            "1.0.0": {"download_url": abs_url}
                        }
                    }
                }
            }

            client._merge_packages(entry, data)
            resolved = client._packages["pkg-1"]["versions"]["1.0.0"]["download_url"]
            assert resolved == abs_url

    def test_remote_flag_set(self):
        """Packages from remote registry should have _registry_remote=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            client = RegistryClient(config)

            entry = RegistryEntry("test", "https://example.com/registry.json")
            data = {"packages": {"pkg-1": {"name": "tool", "versions": {}}}}

            client._merge_packages(entry, data)
            assert client._packages["pkg-1"]["_registry_remote"] is True

    def test_local_flag_set(self):
        """Packages from local registry should have _registry_remote=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            client = RegistryClient(config)

            entry = RegistryEntry("test", os.path.join(tmpdir, "registry.json"))
            data = {"packages": {"pkg-1": {"name": "tool", "versions": {}}}}

            client._merge_packages(entry, data)
            assert client._packages["pkg-1"]["_registry_remote"] is False


class TestConfigRemoteRegistry:
    """Config should save and load remote registry URLs correctly."""

    def test_save_and_load_remote(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            url = "https://raw.githubusercontent.com/org/repo/main/registry.json"

            c = Config()
            c.add_registry("github", url)
            c.save(path)

            loaded = Config.load(path)
            assert len(loaded.registries) == 1
            assert loaded.registries[0].name == "github"
            assert loaded.registries[0].path == url
            assert loaded.registries[0].is_remote is True
