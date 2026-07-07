"""Tests for carton.core.catalogue.sources (extracted from RegistriesSection).

These transports used to live inside the Settings widget where they
were untestable; the extraction contract is pinned here — probe order,
single-package registration outcomes, and local scaffolding.
"""

import io
import json
import os

import pytest

from carton.core.catalogue import sources
from carton.core.catalogue.sources import (
    RESULT_ALREADY_ADDED,
    RESULT_NOT_A_PACKAGE,
    RESULT_REGISTERED,
    CatalogueSourceError,
    probe_github_catalogue_url,
    register_github_single_package,
    register_url_single_package,
    resolve_github_base,
    scaffold_local_catalogue,
)


class _FakeResponse(io.BytesIO):
    def __init__(self, payload, code=200):
        super().__init__(json.dumps(payload).encode("utf-8"))
        self._code = code

    def getcode(self):
        return self._code

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubPersonal:
    instances = []

    def __init__(self, existing=()):
        self.packages = dict.fromkeys(existing)
        self.saved = False
        self.save_error = None
        _StubPersonal.instances.append(self)

    @classmethod
    def load(cls):
        return cls._next

    def contains(self, pkg_id):
        return pkg_id in self.packages

    def add_github_package(self, pkg_id, repo):
        self.packages[pkg_id] = ("github", repo)

    def add_url_package(self, pkg_id, url):
        self.packages[pkg_id] = ("url", url)

    def save(self):
        if self.save_error:
            raise self.save_error
        self.saved = True


@pytest.fixture
def personal(monkeypatch):
    """Route PersonalCatalogue.load() at an in-memory stub."""
    import carton.core.catalogue.personal as personal_mod
    stub = _StubPersonal()
    _StubPersonal._next = stub
    monkeypatch.setattr(personal_mod, "PersonalCatalogue", _StubPersonal)
    return stub


PKG_JSON = {"namespace": "acme", "name": "coolrig"}


class TestResolveGithubBase:
    def test_uses_default_branch(self, monkeypatch):
        monkeypatch.setattr(
            sources, "urlopen",
            lambda req, timeout=10: _FakeResponse({"default_branch": "trunk"}))
        base = resolve_github_base("acme/tools")
        assert base == "https://raw.githubusercontent.com/acme/tools/trunk"

    def test_network_error_raises_source_error(self, monkeypatch):
        def _boom(req, timeout=10):
            raise OSError("rate limited")
        monkeypatch.setattr(sources, "urlopen", _boom)
        with pytest.raises(CatalogueSourceError):
            resolve_github_base("acme/tools")


class TestProbeGithubCatalogueUrl:
    def test_returns_first_candidate_that_answers(self, monkeypatch):
        seen = []

        def _fake(req, timeout=10):
            url = req.full_url
            seen.append(url)
            if url.endswith("/catalogue.json") and "/registry/" not in url:
                return _FakeResponse({})
            raise OSError("404")

        monkeypatch.setattr(sources, "urlopen", _fake)
        resolved = probe_github_catalogue_url("https://raw.test/repo/main")
        assert resolved == "https://raw.test/repo/main/catalogue.json"
        # v5.0 nested candidate must have been tried first.
        assert seen[0].endswith("/registry/catalogue.json")

    def test_returns_none_when_nothing_answers(self, monkeypatch):
        def _boom(req, timeout=10):
            raise OSError("404")
        monkeypatch.setattr(sources, "urlopen", _boom)
        assert probe_github_catalogue_url("https://raw.test/repo/main") is None


class TestRegisterGithubSinglePackage:
    def test_registers_new_package(self, monkeypatch, personal):
        monkeypatch.setattr(sources, "probe_github_package_json",
                            lambda base, timeout=10: dict(PKG_JSON))
        result, pkg_id = register_github_single_package("base", "acme/tools")
        assert result == RESULT_REGISTERED
        assert pkg_id == "acme/coolrig"
        assert personal.packages["acme/coolrig"] == ("github", "acme/tools")
        assert personal.saved

    def test_no_package_json_falls_through(self, monkeypatch, personal):
        monkeypatch.setattr(sources, "probe_github_package_json",
                            lambda base, timeout=10: None)
        assert register_github_single_package("base", "r") == (
            RESULT_NOT_A_PACKAGE, "")

    def test_manifest_without_identity_falls_through(
            self, monkeypatch, personal):
        monkeypatch.setattr(sources, "probe_github_package_json",
                            lambda base, timeout=10: {"name": ""})
        assert register_github_single_package("base", "r") == (
            RESULT_NOT_A_PACKAGE, "")

    def test_already_added_does_not_save(self, monkeypatch, personal):
        personal.packages["acme/coolrig"] = ("github", "old")
        monkeypatch.setattr(sources, "probe_github_package_json",
                            lambda base, timeout=10: dict(PKG_JSON))
        result, pkg_id = register_github_single_package("base", "r")
        assert result == RESULT_ALREADY_ADDED
        assert pkg_id == "acme/coolrig"
        assert not personal.saved

    def test_save_failure_raises_source_error(self, monkeypatch, personal):
        personal.save_error = OSError("read-only")
        monkeypatch.setattr(sources, "probe_github_package_json",
                            lambda base, timeout=10: dict(PKG_JSON))
        with pytest.raises(CatalogueSourceError):
            register_github_single_package("base", "r")


class TestRegisterUrlSinglePackage:
    def test_registers_url_origin(self, monkeypatch, personal):
        monkeypatch.setattr(sources, "urlopen",
                            lambda req, timeout=10: _FakeResponse(PKG_JSON))
        result, pkg_id = register_url_single_package(
            "https://example.invalid/package.json")
        assert result == RESULT_REGISTERED
        assert personal.packages["acme/coolrig"] == (
            "url", "https://example.invalid/package.json")

    def test_fetch_failure_raises_source_error(self, monkeypatch, personal):
        def _boom(req, timeout=10):
            raise OSError("no route")
        monkeypatch.setattr(sources, "urlopen", _boom)
        with pytest.raises(CatalogueSourceError):
            register_url_single_package("https://example.invalid/p.json")

    def test_non_dict_payload_is_not_a_package(self, monkeypatch, personal):
        monkeypatch.setattr(sources, "urlopen",
                            lambda req, timeout=10: _FakeResponse(["x"]))
        assert register_url_single_package("https://e.invalid/p.json") == (
            RESULT_NOT_A_PACKAGE, "")


class TestScaffoldLocalCatalogue:
    def test_creates_v5_catalogue_in_empty_folder(self, tmp_path):
        path, name, rid = scaffold_local_catalogue(str(tmp_path / "cat"))
        assert os.path.basename(path) == "catalogue.json"
        assert name == "cat"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["catalogue_id"] == rid
        assert data["display_name"] == "cat"
        assert data["packages"] == {}
        assert os.path.isdir(os.path.join(os.path.dirname(path), "packages"))

    def test_existing_catalogue_is_adopted_untouched(self, tmp_path):
        existing = tmp_path / "catalogue.json"
        existing.write_text('{"packages": {"a/b": {}}}', encoding="utf-8")
        path, name, rid = scaffold_local_catalogue(str(tmp_path))
        assert path == str(existing)
        assert rid == ""  # id left for CatalogueClient to cache later
        assert json.loads(existing.read_text(encoding="utf-8"))["packages"]

    def test_legacy_registry_is_adopted_untouched(self, tmp_path):
        legacy = tmp_path / "registry.json"
        legacy.write_text("{}", encoding="utf-8")
        path, _, rid = scaffold_local_catalogue(str(tmp_path))
        assert path == str(legacy)
        assert rid == ""
        # No new catalogue.json was scaffolded next to the legacy file.
        assert not (tmp_path / "catalogue.json").exists()
