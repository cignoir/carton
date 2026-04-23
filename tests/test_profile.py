"""Tests for InstallerProfile."""

import json
import os

import pytest

from carton.core.config import Config, CatalogueEntry
from carton.core.profile import InstallerProfile, InvalidProfileError


class TestRoundtrip:
    def test_blank_profile_serializes(self, tmp_path):
        path = tmp_path / "blank.json"
        InstallerProfile.blank().save(str(path))
        loaded = InstallerProfile.load(str(path))
        assert loaded.catalogues == []
        assert loaded.language == "auto"
        assert loaded.auto_check_updates is True
        assert loaded.proxy == ""

    def test_full_profile_round_trip(self, tmp_path):
        path = tmp_path / "studio.json"
        original = InstallerProfile(
            catalogues=[
                CatalogueEntry("/srv/studio/registry.json", display_name="studio-main"),
                CatalogueEntry("https://example.com/registry.json", display_name="ari"),
            ],
            language="ja",
            auto_check_updates=False,
            github_repo="acme/carton-fork",
            proxy="http://proxy.acme.local:8080",
        )
        original.save(str(path))
        loaded = InstallerProfile.load(str(path))
        assert len(loaded.catalogues) == 2
        assert loaded.catalogues[0].display_name == "studio-main"
        assert loaded.catalogues[1].path == "https://example.com/registry.json"
        assert loaded.language == "ja"
        assert loaded.auto_check_updates is False
        assert loaded.github_repo == "acme/carton-fork"
        assert loaded.proxy == "http://proxy.acme.local:8080"

    def test_from_config_snapshots_relevant_fields(self):
        c = Config(
            catalogues=[CatalogueEntry("/x/registry.json", display_name="a")],
            language="en",
            proxy="http://p:80",
        )
        profile = InstallerProfile.from_config(c)
        assert profile.language == "en"
        assert profile.proxy == "http://p:80"
        assert len(profile.catalogues) == 1
        assert profile.catalogues[0].display_name == "a"

    def test_to_dict_omits_install_dir(self):
        # install_dir is intentionally NOT a profile field — verify it
        # never sneaks into the serialized form.
        c = Config(install_dir="/some/local/path")
        d = InstallerProfile.from_config(c).to_dict()
        assert "install_dir" not in d


class TestValidation:
    def test_unknown_field_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(
            json.dumps({"catalogues": [], "weird_key": 1}),
            encoding="utf-8",
        )
        with pytest.raises(InvalidProfileError, match="weird_key"):
            InstallerProfile.load(str(path))

    def test_invalid_language_rejected(self):
        with pytest.raises(InvalidProfileError, match="language"):
            InstallerProfile.from_dict({"language": "klingon"})

    def test_registry_without_name_is_allowed(self):
        """v0.5: display_name is no longer required — catalogue.json is SoT.

        An entry without a name must still round-trip; the display_name
        cache will fill in on first fetch from the catalogue itself.
        """
        profile = InstallerProfile.from_dict({
            "catalogues": [{"path": "/x/r.json"}],
        })
        assert len(profile.catalogues) == 1
        assert profile.catalogues[0].display_name == ""

    def test_registry_without_path_rejected(self):
        with pytest.raises(InvalidProfileError, match="path is required"):
            InstallerProfile.from_dict({
                "catalogues": [{"display_name": "n"}],
            })

    def test_non_object_root_rejected(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(InvalidProfileError, match="JSON object"):
            InstallerProfile.load(str(path))

    def test_missing_file(self, tmp_path):
        with pytest.raises(InvalidProfileError, match="not found"):
            InstallerProfile.load(str(tmp_path / "nope.json"))

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("not json at all", encoding="utf-8")
        with pytest.raises(InvalidProfileError, match="Invalid JSON"):
            InstallerProfile.load(str(path))

    def test_auto_check_updates_must_be_bool(self):
        with pytest.raises(InvalidProfileError, match="boolean"):
            InstallerProfile.from_dict({"auto_check_updates": "yes"})


class TestLegacyKeyAliases:
    """v0.4.x profiles with ``registries`` / ``registry_id`` must still load.

    Profile files are hand-edited and often git-tracked, so we accept the
    legacy keys silently and converge to the v5.0 shape on next save.
    """

    _UUID = "deadbeef-dead-beef-dead-beefdeadbeef"

    def test_registries_alias_accepted(self):
        profile = InstallerProfile.from_dict({
            "registries": [{"name": "studio", "path": "https://ex.com/r.json"}],
        })
        assert len(profile.catalogues) == 1
        # Legacy ``name`` key maps to display_name for UI rendering.
        assert profile.catalogues[0].display_name == "studio"
        assert profile.catalogues[0].path == "https://ex.com/r.json"

    def test_registry_id_alias_accepted(self):
        profile = InstallerProfile.from_dict({
            "catalogues": [
                {"name": "studio", "path": "/x/r.json", "registry_id": self._UUID},
            ],
        })
        assert profile.catalogues[0].catalogue_id == self._UUID

    def test_both_legacy_keys_at_once(self):
        """Full v0.4.x shape: legacy top-level + legacy inner key."""
        profile = InstallerProfile.from_dict({
            "registries": [
                {"name": "studio", "path": "/x/r.json", "registry_id": self._UUID},
            ],
        })
        assert profile.catalogues[0].catalogue_id == self._UUID

    def test_save_rewrites_to_v5_keys(self, tmp_path):
        """Next save() after migration should emit ``catalogues`` — no
        residual ``registries`` key. This is what makes the alias a
        one-shot migration instead of a permanent accommodation."""
        profile = InstallerProfile.from_dict({
            "registries": [
                {"name": "studio", "path": "/x/r.json", "registry_id": self._UUID},
            ],
        })
        path = tmp_path / "out.json"
        profile.save(str(path))
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert "registries" not in saved
        assert "catalogues" in saved
        assert "registry_id" not in saved["catalogues"][0]
        assert saved["catalogues"][0]["catalogue_id"] == self._UUID

    def test_same_file_both_top_level_keys_rejected(self):
        with pytest.raises(InvalidProfileError, match="drop the legacy 'registries'"):
            InstallerProfile.from_dict({
                "catalogues": [{"name": "a", "path": "/a.json"}],
                "registries": [{"name": "b", "path": "/b.json"}],
            })

    def test_same_entry_both_id_keys_rejected(self):
        with pytest.raises(InvalidProfileError, match="drop the legacy key"):
            InstallerProfile.from_dict({
                "catalogues": [{
                    "name": "a", "path": "/a.json",
                    "catalogue_id": self._UUID,
                    "registry_id": self._UUID,
                }],
            })
