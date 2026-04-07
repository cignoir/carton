"""Tests for InstallerProfile."""

import json
import os

import pytest

from carton.core.config import Config, RegistryEntry
from carton.core.profile import InstallerProfile, InvalidProfileError


class TestRoundtrip:
    def test_blank_profile_serializes(self, tmp_path):
        path = tmp_path / "blank.json"
        InstallerProfile.blank().save(str(path))
        loaded = InstallerProfile.load(str(path))
        assert loaded.registries == []
        assert loaded.language == "auto"
        assert loaded.auto_check_updates is True
        assert loaded.proxy == ""

    def test_full_profile_round_trip(self, tmp_path):
        path = tmp_path / "studio.json"
        original = InstallerProfile(
            registries=[
                RegistryEntry("studio-main", "/srv/studio/registry.json"),
                RegistryEntry("ari", "https://example.com/registry.json"),
            ],
            language="ja",
            auto_check_updates=False,
            github_repo="acme/carton-fork",
            proxy="http://proxy.acme.local:8080",
        )
        original.save(str(path))
        loaded = InstallerProfile.load(str(path))
        assert len(loaded.registries) == 2
        assert loaded.registries[0].name == "studio-main"
        assert loaded.registries[1].path == "https://example.com/registry.json"
        assert loaded.language == "ja"
        assert loaded.auto_check_updates is False
        assert loaded.github_repo == "acme/carton-fork"
        assert loaded.proxy == "http://proxy.acme.local:8080"

    def test_from_config_snapshots_relevant_fields(self):
        c = Config(
            registries=[RegistryEntry("a", "/x/registry.json")],
            language="en",
            proxy="http://p:80",
        )
        profile = InstallerProfile.from_config(c)
        assert profile.language == "en"
        assert profile.proxy == "http://p:80"
        assert len(profile.registries) == 1
        assert profile.registries[0].name == "a"

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
            json.dumps({"registries": [], "weird_key": 1}),
            encoding="utf-8",
        )
        with pytest.raises(InvalidProfileError, match="weird_key"):
            InstallerProfile.load(str(path))

    def test_invalid_language_rejected(self):
        with pytest.raises(InvalidProfileError, match="language"):
            InstallerProfile.from_dict({"language": "klingon"})

    def test_registry_without_name_rejected(self):
        with pytest.raises(InvalidProfileError, match="name is required"):
            InstallerProfile.from_dict({
                "registries": [{"path": "/x/r.json"}],
            })

    def test_registry_without_path_rejected(self):
        with pytest.raises(InvalidProfileError, match="path is required"):
            InstallerProfile.from_dict({
                "registries": [{"name": "n"}],
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
