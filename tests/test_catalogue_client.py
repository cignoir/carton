"""Tests for the v5.0 catalogue client (load + merge multiple catalogues)."""

import json
import os
import tempfile

import pytest

from carton.core import github_api
from carton.core.catalogue_client import CatalogueClient
from carton.core.config import Config, CatalogueEntry
from carton.core.migrations import (
    CATALOGUE_FILENAME,
    CATALOGUE_SCHEMA_VERSION,
    LEGACY_REGISTRY_FILENAME,
)
from carton.core.source_cache import SourceCache


_VALID_UUID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


def _v5_catalogue(packages=None, catalogue_id=_VALID_UUID):
    return {
        "schema_version": CATALOGUE_SCHEMA_VERSION,
        "catalogue_id": catalogue_id,
        "packages": packages or {},
    }


def _embedded_pkg(name="tool", versions=None, latest="1.0.0"):
    return {
        "namespace": "test",
        "name": name,
        "display_name": name.title(),
        "origin": {
            "type": "embedded",
            "latest_version": latest,
            "versions": versions or {
                "1.0.0": {
                    "maya_versions": ["2024"],
                    "download_url": "packages/test/{}/1.0.0/{}-1.0.0.zip".format(name, name),
                    "sha256": "a" * 64,
                    "size_bytes": 100,
                    "released_at": "2026-01-01T00:00:00Z",
                },
            },
        },
    }


@pytest.fixture
def isolated_cache(tmp_path):
    return SourceCache(cache_dir=str(tmp_path / "cache"))


class TestCatalogueClientEmbedded:
    def test_loads_embedded_packages_from_local_v5(self, tmp_path, isolated_cache):
        catalogue_path = tmp_path / CATALOGUE_FILENAME
        catalogue_path.write_text(
            json.dumps(_v5_catalogue({"test/tool": _embedded_pkg()})),
            encoding="utf-8",
        )

        config = Config(install_dir=str(tmp_path / "install"))
        config.add_catalogue("studio", str(catalogue_path))

        client = CatalogueClient(config, cache=isolated_cache)
        client.fetch()

        packages = client.get_packages()
        assert "test/tool" in packages
        pkg = packages["test/tool"]
        # Resolved to absolute path on disk.
        assert pkg["versions"]["1.0.0"]["download_url"].endswith(
            os.path.normpath("packages/test/tool/1.0.0/tool-1.0.0.zip")
        )
        assert pkg["latest_version"] == "1.0.0"
        assert pkg["_catalogue_name"] == "studio"
        assert pkg["_catalogue_remote"] is False
        assert pkg["_origin"]["type"] == "embedded"

    def test_auto_migrates_legacy_registry_json(self, tmp_path, isolated_cache):
        # Place a v4.0 registry.json — client should migrate it to
        # catalogue.json on first load.
        legacy_path = tmp_path / LEGACY_REGISTRY_FILENAME
        legacy_path.write_text(json.dumps({
            "schema_version": "4.0",
            "registry_id": _VALID_UUID,
            "packages": {
                "test/tool": {
                    "namespace": "test",
                    "name": "tool",
                    "display_name": "Tool",
                    "type": "python_package",
                    "description": "",
                    "author": "",
                    "latest_version": "1.0.0",
                    "versions": {
                        "1.0.0": {
                            "maya_versions": ["2024"],
                            "download_url": "packages/test/tool/1.0.0/tool-1.0.0.zip",
                            "released_at": "2026-01-01T00:00:00Z",
                        },
                    },
                },
            },
        }), encoding="utf-8")

        config = Config(install_dir=str(tmp_path / "install"))
        config.add_catalogue("studio", str(legacy_path))

        client = CatalogueClient(config, cache=isolated_cache)
        client.fetch()

        # The catalogue.json sibling now exists.
        assert (tmp_path / CATALOGUE_FILENAME).exists()
        # The original registry.json has been backed up.
        backups = [p for p in os.listdir(str(tmp_path))
                   if p.startswith("registry.json.bak-v0.4.")]
        assert len(backups) == 1

        # Packages came through.
        assert "test/tool" in client.get_packages()

    def test_first_catalogue_wins_on_id_collision(self, tmp_path, isolated_cache):
        cat_a = tmp_path / "a" / CATALOGUE_FILENAME
        cat_a.parent.mkdir()
        cat_a.write_text(json.dumps(_v5_catalogue({
            "test/tool": _embedded_pkg(name="tool", versions={
                "1.0.0": {
                    "maya_versions": ["2024"],
                    "download_url": "first.zip",
                    "released_at": "2026-01-01T00:00:00Z",
                },
            }),
        })), encoding="utf-8")

        cat_b = tmp_path / "b" / CATALOGUE_FILENAME
        cat_b.parent.mkdir()
        cat_b.write_text(json.dumps(_v5_catalogue({
            "test/tool": _embedded_pkg(name="tool", versions={
                "1.0.0": {
                    "maya_versions": ["2024"],
                    "download_url": "second.zip",
                    "released_at": "2026-02-01T00:00:00Z",
                },
            }),
        }, catalogue_id="bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb")), encoding="utf-8")

        config = Config(install_dir=str(tmp_path / "install"))
        config.add_catalogue("a", str(cat_a))
        config.add_catalogue("b", str(cat_b))

        client = CatalogueClient(config, cache=isolated_cache)
        client.fetch()

        pkg = client.get_packages()["test/tool"]
        assert pkg["_catalogue_name"] == "a"
        assert pkg["versions"]["1.0.0"]["download_url"].endswith("first.zip")


class TestCatalogueClientGithub:
    def test_loads_github_origin_versions(self, tmp_path, isolated_cache, monkeypatch):
        # Stub the github_api so no real network is hit.
        monkeypatch.setattr(github_api, "list_releases", lambda repo, cache=None: [
            {"tag_name": "v1.0.0", "draft": False, "assets": [
                {"name": "tool-1.0.0.zip",
                 "browser_download_url": "https://example.com/tool-1.0.0.zip",
                 "size": 99},
            ], "published_at": "2026-01-01T00:00:00Z"},
        ])
        monkeypatch.setattr(github_api, "list_tags", lambda repo, cache=None: [])
        monkeypatch.setattr(github_api, "get_default_branch",
                            lambda repo, cache=None: "main")
        monkeypatch.setattr(github_api, "fetch_raw_text",
                            lambda url, timeout=15: "")

        catalogue_path = tmp_path / CATALOGUE_FILENAME
        catalogue_path.write_text(
            json.dumps(_v5_catalogue({
                "test/tool": {
                    "namespace": "test",
                    "name": "tool",
                    "origin": {"type": "github", "repo": "user/tool"},
                },
            })), encoding="utf-8",
        )

        config = Config(install_dir=str(tmp_path / "install"))
        config.add_catalogue("studio", str(catalogue_path))

        client = CatalogueClient(config, cache=isolated_cache)
        client.fetch()

        pkg = client.get_packages()["test/tool"]
        assert "1.0.0" in pkg["versions"]
        v = pkg["versions"]["1.0.0"]
        assert v["download_url"] == "https://example.com/tool-1.0.0.zip"
        assert v["_pinned"] is False
        assert pkg["_origin"]["type"] == "github"

    def test_skips_packages_with_unknown_origin_type(self, tmp_path, isolated_cache):
        catalogue_path = tmp_path / CATALOGUE_FILENAME
        catalogue_path.write_text(json.dumps(_v5_catalogue({
            "test/good": _embedded_pkg(name="good"),
            "test/bad": {"namespace": "test", "name": "bad",
                         "origin": {"type": "future-format"}},
        })), encoding="utf-8")

        config = Config(install_dir=str(tmp_path / "install"))
        config.add_catalogue("studio", str(catalogue_path))

        client = CatalogueClient(config, cache=isolated_cache)
        client.fetch()
        packages = client.get_packages()
        assert "test/good" in packages
        assert "test/bad" not in packages


class TestCatalogueClientPersonal:
    """Personal catalogue merge — ``~/.carton/personal_catalogue.json`` gets
    folded into the merged package dict alongside subscribed catalogues.

    Hermeticity: every test injects an explicit :class:`PersonalCatalogue`
    instance or ``personal_catalogue_path`` so no test reads from the
    developer's actual home directory.
    """

    def _make_client(self, tmp_path, cache, personal=None, subscribed=None,
                     github_stub=None, monkeypatch=None):
        config = Config(install_dir=str(tmp_path / "install"))
        for name, catalogue_path in (subscribed or []):
            config.add_catalogue(name, str(catalogue_path))
        if github_stub is not None:
            # Personal github origins will try to hit the GitHub API via
            # the Origin layer when resolving versions. Stub it out so
            # the tests don't hit the network.
            monkeypatch.setattr(github_api, "list_releases",
                                lambda repo, cache=None: github_stub.get(repo, []))
            monkeypatch.setattr(github_api, "list_tags",
                                lambda repo, cache=None: [])
            monkeypatch.setattr(github_api, "get_default_branch",
                                lambda repo, cache=None: "main")
            monkeypatch.setattr(github_api, "fetch_raw_text",
                                lambda url, timeout=15: "")
        return CatalogueClient(config, cache=cache, personal_catalogue=personal)

    def test_merges_personal_github_package(self, tmp_path, isolated_cache, monkeypatch):
        from carton.core.personal_catalogue import (
            PERSONAL_DISPLAY_NAME,
            PersonalCatalogue,
        )

        personal = PersonalCatalogue()
        personal.add_github_package("alice/tool", "alice/tool")

        client = self._make_client(
            tmp_path, isolated_cache, personal=personal,
            github_stub={"alice/tool": [
                {"tag_name": "v1.0.0", "draft": False, "assets": [
                    {"name": "tool-1.0.0.zip",
                     "browser_download_url": "https://example.com/tool-1.0.0.zip",
                     "size": 42},
                ], "published_at": "2026-01-01T00:00:00Z"},
            ]},
            monkeypatch=monkeypatch,
        )
        client.fetch()

        packages = client.get_packages()
        assert "alice/tool" in packages
        pkg = packages["alice/tool"]
        assert pkg["_catalogue_name"] == PERSONAL_DISPLAY_NAME
        assert pkg["_catalogue_remote"] is False
        assert pkg["_origin"]["type"] == "github"
        assert pkg["_catalogue_id"] == personal.catalogue_id

    def test_empty_personal_is_noop(self, tmp_path, isolated_cache):
        """Empty personal catalogue must not mask subscribed catalogue data."""
        from carton.core.personal_catalogue import PersonalCatalogue

        catalogue_path = tmp_path / CATALOGUE_FILENAME
        catalogue_path.write_text(
            json.dumps(_v5_catalogue({"test/tool": _embedded_pkg()})),
            encoding="utf-8",
        )
        client = self._make_client(
            tmp_path, isolated_cache,
            personal=PersonalCatalogue(),
            subscribed=[("studio", catalogue_path)],
        )
        client.fetch()

        packages = client.get_packages()
        assert list(packages.keys()) == ["test/tool"]
        assert packages["test/tool"]["_catalogue_name"] == "studio"

    def test_subscribed_catalogue_wins_on_collision(self, tmp_path, isolated_cache, monkeypatch):
        """If a package id exists in both, the subscribed catalogue wins.

        Personal is a user's ad-hoc fallback; an official source
        should always take precedence to keep behaviour predictable.
        """
        from carton.core.personal_catalogue import PersonalCatalogue

        catalogue_path = tmp_path / CATALOGUE_FILENAME
        catalogue_path.write_text(
            json.dumps(_v5_catalogue({"alice/tool": _embedded_pkg(name="tool")})),
            encoding="utf-8",
        )

        personal = PersonalCatalogue()
        personal.add_github_package("alice/tool", "alice/tool")

        client = self._make_client(
            tmp_path, isolated_cache, personal=personal,
            subscribed=[("studio", catalogue_path)],
            github_stub={}, monkeypatch=monkeypatch,
        )
        client.fetch()

        pkg = client.get_packages()["alice/tool"]
        # Subscribed catalogue's embedded entry, not personal's github.
        assert pkg["_catalogue_name"] == "studio"
        assert pkg["_origin"]["type"] == "embedded"

    def test_loads_personal_from_explicit_path(self, tmp_path, isolated_cache, monkeypatch):
        """``personal_catalogue_path`` param bypasses the default ~/.carton/ path."""
        from carton.core.personal_catalogue import PersonalCatalogue

        personal_path = tmp_path / "alt" / "personal_catalogue.json"
        cat = PersonalCatalogue()
        cat.add_github_package("alice/tool", "alice/tool")
        cat.save(str(personal_path))

        # Stub github_api to keep the test offline.
        monkeypatch.setattr(github_api, "list_releases",
                            lambda repo, cache=None: [])
        monkeypatch.setattr(github_api, "list_tags",
                            lambda repo, cache=None: [])
        monkeypatch.setattr(github_api, "get_default_branch",
                            lambda repo, cache=None: "main")
        monkeypatch.setattr(github_api, "fetch_raw_text",
                            lambda url, timeout=15: "")

        config = Config(install_dir=str(tmp_path / "install"))
        client = CatalogueClient(
            config, cache=isolated_cache,
            personal_catalogue_path=str(personal_path),
        )
        client.fetch()

        assert "alice/tool" in client.get_packages()

    def test_corrupt_personal_file_does_not_crash_stub(self, tmp_path, isolated_cache):
        # Kept as a stub marker — real assertion lives below; this split
        # was introduced so the projection tests can append without
        # disturbing the existing class layout. Left as a no-op:
        pass


class TestCatalogueClientUrlOrigin:
    """URL origin projection — CatalogueClient must fold the remote
    package.json's fields into the legacy-shape dict so the UI can render
    cards pre-install without knowing it's a url origin under the hood."""

    def _write_catalogue(self, tmp_path, url):
        path = tmp_path / CATALOGUE_FILENAME
        path.write_text(
            json.dumps(_v5_catalogue(packages={
                "studio/tool": {
                    "origin": {"type": "url", "url": url},
                },
            })),
            encoding="utf-8",
        )
        return path

    def _stub_urlopen(self, monkeypatch, payload):
        """Replace url_origin.urlopen with a fixed JSON response."""
        from carton.core.origins import url_origin as url_mod

        class _Resp:
            def read(self_inner):
                return json.dumps(payload).encode("utf-8")

        monkeypatch.setattr(url_mod, "urlopen",
                            lambda req, timeout=10: _Resp())

    def test_projects_versions_from_remote_package_json(
        self, tmp_path, isolated_cache, monkeypatch,
    ):
        self._stub_urlopen(monkeypatch, {
            "namespace": "studio",
            "name": "tool",
            "display_name": "Tool",
            "version": "1.5.0",
            "maya_versions": ["2025"],
            "download_url": "https://example.com/tool-1.5.0.zip",
            "sha256": "f" * 64,
            "size_bytes": 42,
        })
        path = self._write_catalogue(tmp_path, "https://example.com/tool/package.json")
        cfg = Config(catalogues=[CatalogueEntry("url-cat", str(path),
                                                catalogue_id=_VALID_UUID)])
        client = CatalogueClient(cfg, cache=isolated_cache)
        client.fetch()

        pkgs = client.get_packages()
        assert "studio/tool" in pkgs
        entry = pkgs["studio/tool"]
        assert entry["latest_version"] == "1.5.0"
        versions = entry["versions"]
        assert list(versions.keys()) == ["1.5.0"]
        v = versions["1.5.0"]
        assert v["download_url"] == "https://example.com/tool-1.5.0.zip"
        assert v["sha256"] == "f" * 64
        assert v["_pinned"] is True
        assert v["size_bytes"] == 42

    def test_hydrates_display_fields_from_manifest(
        self, tmp_path, isolated_cache, monkeypatch,
    ):
        """package.json display fields must win over the catalogue entry
        (the manifest is the SoT for url origins)."""
        self._stub_urlopen(monkeypatch, {
            "namespace": "studio",
            "name": "tool",
            "display_name": "Super Tool",
            "description": "from manifest",
            "icon": "🔧",
            "type": "python_package",
            "author": "alice",
            "version": "1.0.0",
            "download_url": "https://example.com/x.zip",
        })
        path = self._write_catalogue(tmp_path, "https://example.com/tool/package.json")
        cfg = Config(catalogues=[CatalogueEntry("url-cat", str(path),
                                                catalogue_id=_VALID_UUID)])
        client = CatalogueClient(cfg, cache=isolated_cache)
        client.fetch()

        entry = client.get_packages()["studio/tool"]
        assert entry["display_name"] == "Super Tool"
        assert entry["description"] == "from manifest"
        assert entry["icon"] == "🔧"
        assert entry["author"] == "alice"
        assert entry["type"] == "python_package"

    def test_unpinned_url_origin_flagged(
        self, tmp_path, isolated_cache, monkeypatch,
    ):
        """When the manifest has no sha256, _pinned is False so the
        downloader's TOFU path kicks in."""
        self._stub_urlopen(monkeypatch, {
            "name": "tool", "namespace": "studio",
            "version": "1.0.0",
            "download_url": "https://example.com/x.zip",
        })
        path = self._write_catalogue(tmp_path, "https://example.com/tool/package.json")
        cfg = Config(catalogues=[CatalogueEntry("url-cat", str(path),
                                                catalogue_id=_VALID_UUID)])
        client = CatalogueClient(cfg, cache=isolated_cache)
        client.fetch()

        v = client.get_packages()["studio/tool"]["versions"]["1.0.0"]
        assert v["_pinned"] is False
        assert "sha256" not in v or v.get("sha256") == ""

    def test_fetch_failure_yields_empty_versions(
        self, tmp_path, isolated_cache, monkeypatch,
    ):
        """A url origin whose manifest 404s should still register the
        package but produce an empty versions dict (no crash, card
        degrades to 'unavailable')."""
        from carton.core.origins import url_origin as url_mod
        from carton.compat_urllib import URLError

        def _boom(req, timeout=10):
            raise URLError("connection refused")

        monkeypatch.setattr(url_mod, "urlopen", _boom)

        path = self._write_catalogue(tmp_path, "https://example.com/tool/package.json")
        cfg = Config(catalogues=[CatalogueEntry("url-cat", str(path),
                                                catalogue_id=_VALID_UUID)])
        client = CatalogueClient(cfg, cache=isolated_cache)
        client.fetch()

        pkgs = client.get_packages()
        assert "studio/tool" in pkgs
        assert pkgs["studio/tool"]["versions"] == {}


class TestCatalogueClientLocalOrigin:
    """Local origin projection — same shape as url origin but reads from
    disk. Covers happy-path projection plus missing-manifest degradation."""

    def _write_catalogue(self, tmp_path, origin_path):
        path = tmp_path / "cat" / CATALOGUE_FILENAME
        os.makedirs(path.parent, exist_ok=True)
        path.write_text(
            json.dumps(_v5_catalogue(packages={
                "studio/local_tool": {
                    "origin": {"type": "local", "path": origin_path},
                },
            })),
            encoding="utf-8",
        )
        return path

    def _write_manifest(self, dir_path, body):
        os.makedirs(dir_path, exist_ok=True)
        path = os.path.join(dir_path, "package.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(body, f)

    def test_projects_version_and_resolves_relative_artifact(
        self, tmp_path, isolated_cache,
    ):
        src = tmp_path / "src"
        self._write_manifest(str(src), {
            "namespace": "studio",
            "name": "local_tool",
            "display_name": "Local Tool",
            "version": "0.1.0",
            "download_url": "local_tool-0.1.0.zip",
            "sha256": "b" * 64,
        })
        path = self._write_catalogue(tmp_path, str(src))
        cfg = Config(catalogues=[CatalogueEntry("local-cat", str(path),
                                                catalogue_id=_VALID_UUID)])
        client = CatalogueClient(cfg, cache=isolated_cache)
        client.fetch()

        entry = client.get_packages()["studio/local_tool"]
        assert entry["latest_version"] == "0.1.0"
        assert entry["display_name"] == "Local Tool"
        v = entry["versions"]["0.1.0"]
        expected = os.path.normpath(os.path.join(str(src), "local_tool-0.1.0.zip"))
        assert v["download_url"] == expected
        assert v["_pinned"] is True

    def test_missing_manifest_directory_yields_empty_versions(
        self, tmp_path, isolated_cache,
    ):
        """Local origin pointing at a nonexistent path should register
        the package (so the UI can show 'source moved') but hold empty
        versions — no crash."""
        path = self._write_catalogue(tmp_path, str(tmp_path / "does_not_exist"))
        cfg = Config(catalogues=[CatalogueEntry("local-cat", str(path),
                                                catalogue_id=_VALID_UUID)])
        client = CatalogueClient(cfg, cache=isolated_cache)
        client.fetch()

        entry = client.get_packages()["studio/local_tool"]
        assert entry["versions"] == {}

    def test_corrupt_personal_file_does_not_crash(self, tmp_path, isolated_cache):
        """A garbled personal_catalogue.json must not break subscribed catalogues."""
        personal_path = tmp_path / "personal_catalogue.json"
        personal_path.write_text("definitely-not-json", encoding="utf-8")

        catalogue_path = tmp_path / CATALOGUE_FILENAME
        catalogue_path.write_text(
            json.dumps(_v5_catalogue({"test/tool": _embedded_pkg()})),
            encoding="utf-8",
        )

        config = Config(install_dir=str(tmp_path / "install"))
        config.add_catalogue("studio", str(catalogue_path))

        client = CatalogueClient(
            config, cache=isolated_cache,
            personal_catalogue_path=str(personal_path),
        )
        client.fetch()
        # Subscribed catalogue still works.
        assert "test/tool" in client.get_packages()
