"""Tests for :mod:`carton.core.personal_catalogue` (Step 4-B).

Personal catalogue is the receptacle for URL 直指定 single-package repos
added via Settings > Add. It shares v5.0 catalogue.json shape so that
future CatalogueClient merge work can treat it uniformly with subscribed
catalogues.

Coverage:

* storage round-trip (``save`` → ``load`` → same shape)
* fresh instance gets a generated ``catalogue_id`` (UUID v4 form)
* ``add_github_package`` / ``add_url_package`` happy path + idempotency
  (existing pkg_id wins, no silent overwrite)
* ``remove`` semantics
* ``to_dict`` matches v5.0 catalogue.json shape (schema_version,
  catalogue_id, packages keys)
* ``load`` of a missing file returns a fresh empty instance
* corrupted file on disk does not crash — returns an empty instance
* ``default_path`` lives under the user home (install_dir independence)
"""

import json
import os

import pytest

from carton.core import personal_catalogue as pc
from carton.core.registry_id import is_valid_registry_id


class TestDefaultPath:
    def test_under_user_home(self):
        """Personal catalogue must live under ~, not install_dir."""
        path = pc.default_path()
        assert path.endswith(pc.PERSONAL_CATALOGUE_FILENAME)
        # Expanded user home is the parent of .carton directory.
        assert os.path.dirname(path).endswith(".carton")
        home = os.path.expanduser("~")
        assert path.startswith(home)


class TestDerivePkgId:
    def test_valid_package(self):
        data = {"namespace": "alice", "name": "tool"}
        assert pc.derive_pkg_id(data) == "alice/tool"

    def test_lowercases_both_components(self):
        data = {"namespace": "Alice", "name": "Tool"}
        assert pc.derive_pkg_id(data) == "alice/tool"

    def test_strips_whitespace(self):
        data = {"namespace": "  alice ", "name": "tool "}
        assert pc.derive_pkg_id(data) == "alice/tool"

    def test_missing_namespace_returns_empty(self):
        data = {"name": "tool"}
        assert pc.derive_pkg_id(data) == ""

    def test_missing_name_returns_empty(self):
        data = {"namespace": "alice"}
        assert pc.derive_pkg_id(data) == ""

    def test_non_dict_returns_empty(self):
        assert pc.derive_pkg_id(None) == ""
        assert pc.derive_pkg_id("not a dict") == ""
        assert pc.derive_pkg_id(["list"]) == ""


class TestFreshInstance:
    def test_generates_catalogue_id(self):
        cat = pc.PersonalCatalogue()
        assert is_valid_registry_id(cat.catalogue_id)

    def test_preserves_explicit_catalogue_id(self):
        fixed = "12345678-1234-1234-1234-123456789abc"
        cat = pc.PersonalCatalogue(catalogue_id=fixed)
        assert cat.catalogue_id == fixed

    def test_default_display_name(self):
        cat = pc.PersonalCatalogue()
        assert cat.display_name == pc.PERSONAL_DISPLAY_NAME

    def test_empty_packages(self):
        cat = pc.PersonalCatalogue()
        assert cat.packages == {}


class TestAddGithub:
    def test_happy_path(self):
        cat = pc.PersonalCatalogue()
        assert cat.add_github_package("alice/tool", "alice/tool") is True
        assert cat.contains("alice/tool")
        entry = cat.packages["alice/tool"]
        assert entry["origin"] == {"type": "github", "repo": "alice/tool"}

    def test_duplicate_pkg_id_rejected(self):
        """No silent overwrite — second add returns False, data unchanged."""
        cat = pc.PersonalCatalogue()
        cat.add_github_package("alice/tool", "alice/tool")
        added = cat.add_github_package("alice/tool", "other/different")
        assert added is False
        assert cat.packages["alice/tool"]["origin"]["repo"] == "alice/tool"

    def test_empty_args_rejected(self):
        cat = pc.PersonalCatalogue()
        assert cat.add_github_package("", "alice/tool") is False
        assert cat.add_github_package("alice/tool", "") is False
        assert cat.packages == {}


class TestAddUrl:
    def test_happy_path(self):
        cat = pc.PersonalCatalogue()
        url = "https://example.com/tool/package.json"
        assert cat.add_url_package("thirdparty/tool", url) is True
        entry = cat.packages["thirdparty/tool"]
        assert entry["origin"] == {"type": "url", "url": url}

    def test_duplicate_rejected(self):
        cat = pc.PersonalCatalogue()
        cat.add_url_package("a/b", "https://a/b")
        assert cat.add_url_package("a/b", "https://c/d") is False


class TestRemove:
    def test_existing(self):
        cat = pc.PersonalCatalogue()
        cat.add_github_package("alice/tool", "alice/tool")
        assert cat.remove("alice/tool") is True
        assert not cat.contains("alice/tool")

    def test_missing_is_noop(self):
        cat = pc.PersonalCatalogue()
        assert cat.remove("ghost/not-there") is False


class TestToDict:
    def test_v5_catalogue_shape(self):
        cat = pc.PersonalCatalogue()
        cat.add_github_package("alice/tool", "alice/tool")
        d = cat.to_dict()
        assert d["schema_version"] == pc.SCHEMA_VERSION
        assert d["catalogue_id"] == cat.catalogue_id
        assert d["display_name"] == pc.PERSONAL_DISPLAY_NAME
        assert d["packages"]["alice/tool"]["origin"]["type"] == "github"


class TestRoundTrip:
    def test_save_load(self, tmp_path):
        path = tmp_path / "personal_catalogue.json"
        cat = pc.PersonalCatalogue()
        cat.add_github_package("alice/tool", "alice/tool")
        cat.add_url_package("beta/tool", "https://example.com/beta.json")
        cat.save(str(path))

        reloaded = pc.PersonalCatalogue.load(str(path))
        assert reloaded.catalogue_id == cat.catalogue_id
        assert reloaded.contains("alice/tool")
        assert reloaded.contains("beta/tool")
        assert reloaded.packages["beta/tool"]["origin"]["url"] == \
            "https://example.com/beta.json"

    def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "nested" / "deep" / "personal_catalogue.json"
        cat = pc.PersonalCatalogue()
        cat.save(str(nested))
        assert nested.exists()

    def test_save_is_valid_json(self, tmp_path):
        path = tmp_path / "personal_catalogue.json"
        cat = pc.PersonalCatalogue()
        cat.add_github_package("a/b", "a/b")
        cat.save(str(path))
        with open(str(path), "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == pc.SCHEMA_VERSION


class TestLoadEdgeCases:
    def test_missing_file_returns_empty(self, tmp_path):
        path = tmp_path / "does_not_exist.json"
        cat = pc.PersonalCatalogue.load(str(path))
        assert cat.packages == {}
        assert is_valid_registry_id(cat.catalogue_id)

    def test_corrupt_file_returns_empty(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("not-json-at-all", encoding="utf-8")
        cat = pc.PersonalCatalogue.load(str(path))
        assert cat.packages == {}
        # New catalogue_id gets generated so a follow-up save rewrites
        # the broken file with a valid shape.
        assert is_valid_registry_id(cat.catalogue_id)

    def test_preserves_catalogue_id_across_load(self, tmp_path):
        path = tmp_path / "personal_catalogue.json"
        cat = pc.PersonalCatalogue()
        original_id = cat.catalogue_id
        cat.save(str(path))
        reloaded = pc.PersonalCatalogue.load(str(path))
        assert reloaded.catalogue_id == original_id
