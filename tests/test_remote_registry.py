"""Tests for remote (URL-based) registry support."""

import json
import os
import tempfile

import pytest

from carton.core.config import Config, CatalogueEntry, _is_url
from carton.core.publisher import Publisher, RemoteMirrorMissingError


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


class TestCatalogueEntryRemote:
    def test_is_remote_url(self):
        e = CatalogueEntry("test", "https://example.com/reg/registry.json")
        assert e.is_remote is True

    def test_is_remote_local(self):
        e = CatalogueEntry("test", "/some/path/registry.json")
        assert e.is_remote is False

    def test_url_not_normpathed(self):
        """URLs should not be mangled by os.path.normpath."""
        url = "https://raw.githubusercontent.com/org/repo/main/registry.json"
        e = CatalogueEntry("test", url)
        assert e.path == url

    def test_base_dir_url(self):
        e = CatalogueEntry("test", "https://example.com/registry/registry.json")
        assert e.base_dir == "https://example.com/registry/"

    def test_base_dir_url_nested(self):
        e = CatalogueEntry("test", "https://raw.githubusercontent.com/org/repo/main/registry.json")
        assert e.base_dir == "https://raw.githubusercontent.com/org/repo/main/"

    def test_base_dir_local(self):
        e = CatalogueEntry("test", "/some/dir/registry.json")
        assert e.base_dir == os.path.normpath("/some/dir")


class TestPublisherRemoteGuard:
    """Publisher rejects remote publishes that have no local mirror to route to."""

    def _make_publisher(self):
        config = Config(install_dir=tempfile.mkdtemp())
        return Publisher(config)

    def test_publish_to_remote_without_id_raises_mirror_missing(self, monkeypatch):
        """A remote without an exposed ``registry_id`` cannot be mirrored."""
        publisher = self._make_publisher()
        # Prevent the probe from making a real network call.
        monkeypatch.setattr(
            Publisher, "_probe_remote_catalogue_id", staticmethod(lambda e: ""),
        )
        remote_entry = CatalogueEntry("remote", "https://example.com/registry.json")
        with pytest.raises(RemoteMirrorMissingError) as excinfo:
            publisher.publish({}, remote_entry)
        assert excinfo.value.reason == "no_remote_id"

    def test_publish_to_remote_without_mirror_raises_mirror_missing(self, monkeypatch):
        """Known remote id, but no local entry shares it."""
        publisher = self._make_publisher()
        rid = "11111111-2222-4333-8444-555555555555"
        monkeypatch.setattr(
            Publisher, "_probe_remote_catalogue_id", staticmethod(lambda e: rid),
        )
        remote_entry = CatalogueEntry("remote", "https://example.com/registry.json")
        with pytest.raises(RemoteMirrorMissingError) as excinfo:
            publisher.publish({}, remote_entry)
        assert excinfo.value.reason == "no_local_mirror"
        assert excinfo.value.remote_id == rid

    def test_unpublish_from_remote_without_mirror_raises(self, monkeypatch):
        publisher = self._make_publisher()
        monkeypatch.setattr(
            Publisher, "_probe_remote_catalogue_id", staticmethod(lambda e: ""),
        )
        remote_entry = CatalogueEntry("remote", "https://example.com/registry.json")
        with pytest.raises(RemoteMirrorMissingError):
            publisher.unpublish("fake-id", remote_entry)

    def test_find_published_skips_remote(self):
        """find_published_registries should skip remote registries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            config.add_catalogue("remote", "https://example.com/registry.json")

            # Also add a local registry that doesn't exist
            config.add_catalogue("local", os.path.join(tmpdir, "nonexistent.json"))

            publisher = Publisher(config)
            results = publisher.find_published_registries("some-uuid")
            # Both should be skipped (remote skipped, local doesn't exist)
            assert results == []


# URL resolution and remote/local flag attachment used to be covered
# here by poking RegistryClient._merge_packages directly. CatalogueClient
# does the same projection via ``_build_legacy_shape`` +
# ``_project_embedded_versions`` — tests/test_catalogue_client.py covers
# the local/relative-path side via a live embedded catalogue, and the
# remote-flag counterpart is exercised indirectly through the fetch +
# merge path in this file's ``TestConfigRemoteRegistry``. RegistryClient
# itself is slated for removal once this import is the last holdout.


class TestConfigRemoteRegistry:
    """Config should save and load remote registry URLs correctly."""

    def test_save_and_load_remote(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            url = "https://raw.githubusercontent.com/org/repo/main/registry.json"

            c = Config()
            c.add_catalogue("github", url)
            c.save(path)

            loaded = Config.load(path)
            assert len(loaded.catalogues) == 1
            assert loaded.catalogues[0].name == "github"
            assert loaded.catalogues[0].path == url
            assert loaded.catalogues[0].is_remote is True
