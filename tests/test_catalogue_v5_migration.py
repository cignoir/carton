"""Tests for v4.0 registry → v5.0 catalogue migration."""

import json
import os

import pytest

from carton.core.migrations import (
    CATALOGUE_FILENAME,
    CATALOGUE_SCHEMA_VERSION,
    LEGACY_REGISTRY_FILENAME,
    migrate_local_registry_file_to_catalogue,
    migrate_registry_to_catalogue,
)


_VALID_UUID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


def _v4_registry(packages=None):
    return {
        "schema_version": "4.0",
        "registry_id": _VALID_UUID,
        "packages": packages or {},
    }


class TestMigrateRegistryToCatalogue:
    def test_passthrough_when_already_v5(self):
        data = {
            "schema_version": CATALOGUE_SCHEMA_VERSION,
            "catalogue_id": _VALID_UUID,
            "packages": {},
        }
        out, was = migrate_registry_to_catalogue(data)
        assert was is False
        assert out is data

    def test_v4_registry_id_carries_to_catalogue_id(self):
        data = _v4_registry()
        out, was = migrate_registry_to_catalogue(data)
        assert was is True
        assert out["catalogue_id"] == _VALID_UUID
        assert out["schema_version"] == CATALOGUE_SCHEMA_VERSION

    def test_missing_id_gets_stamped(self):
        data = {"schema_version": "4.0", "packages": {}}
        out, was = migrate_registry_to_catalogue(data)
        assert was is True
        assert out["catalogue_id"]  # non-empty UUID

    def test_stamp_id_false_keeps_id_empty(self):
        data = {"schema_version": "4.0", "packages": {}}
        out, _ = migrate_registry_to_catalogue(data, stamp_id=False)
        assert out["catalogue_id"] == ""

    def test_package_versions_move_into_origin(self):
        data = _v4_registry({
            "mystudio/rigger": {
                "namespace": "mystudio",
                "name": "rigger",
                "display_name": "Rigger",
                "type": "python_package",
                "description": "A rig tool",
                "author": "tn",
                "latest_version": "1.0.0",
                "versions": {
                    "1.0.0": {
                        "maya_versions": ["2024", "2025"],
                        "download_url": "packages/mystudio/rigger/1.0.0/rigger-1.0.0.zip",
                        "sha256": "a" * 64,
                        "size_bytes": 12345,
                        "released_at": "2026-03-01T00:00:00Z",
                    },
                },
            },
        })
        out, _ = migrate_registry_to_catalogue(data)
        pkg = out["packages"]["mystudio/rigger"]
        # versions is no longer at the top level — it's inside origin.
        assert "versions" not in pkg
        assert "latest_version" not in pkg
        assert pkg["origin"]["type"] == "embedded"
        assert pkg["origin"]["latest_version"] == "1.0.0"
        assert pkg["origin"]["versions"]["1.0.0"]["sha256"] == "a" * 64

    def test_display_metadata_preserved_at_package_level(self):
        data = _v4_registry({
            "mystudio/rigger": {
                "namespace": "mystudio",
                "name": "rigger",
                "display_name": "Rigger",
                "type": "python_package",
                "description": "desc",
                "author": "tn",
                "icon": "🔧",
                "tags": ["rig"],
                "first_published_by": "tn",
                "first_published_at": "2026-01-01T00:00:00Z",
                "versions": {},
            },
        })
        out, _ = migrate_registry_to_catalogue(data)
        pkg = out["packages"]["mystudio/rigger"]
        # UI-relevant fields stay at package level so the catalogue can
        # render package cards without downloading the artifact zip.
        assert pkg["display_name"] == "Rigger"
        assert pkg["description"] == "desc"
        assert pkg["icon"] == "🔧"
        assert pkg["tags"] == ["rig"]
        assert pkg["first_published_by"] == "tn"

    def test_idempotent_after_one_pass(self):
        data = _v4_registry({"a/b": {"name": "b", "versions": {}}})
        once, _ = migrate_registry_to_catalogue(data)
        twice, was = migrate_registry_to_catalogue(once)
        assert was is False
        assert twice is once

    def test_invalid_input_returns_empty_catalogue(self):
        out, was = migrate_registry_to_catalogue("not a dict")
        assert was is True
        assert out["schema_version"] == CATALOGUE_SCHEMA_VERSION
        assert out["packages"] == {}

    def test_carries_display_name_and_last_updated(self):
        data = _v4_registry()
        data["display_name"] = "Studio Main"
        data["last_updated"] = "2026-04-20T00:00:00Z"
        out, _ = migrate_registry_to_catalogue(data)
        assert out["display_name"] == "Studio Main"
        assert out["last_updated"] == "2026-04-20T00:00:00Z"


class TestMigrateLocalRegistryFile:
    def test_writes_catalogue_json_and_backs_up_legacy(self, tmp_path):
        legacy = tmp_path / LEGACY_REGISTRY_FILENAME
        legacy.write_text(json.dumps(_v4_registry({
            "a/b": {"name": "b", "versions": {}},
        })), encoding="utf-8")

        out_path = migrate_local_registry_file_to_catalogue(str(legacy))
        assert os.path.basename(out_path) == CATALOGUE_FILENAME
        assert os.path.exists(out_path)

        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == CATALOGUE_SCHEMA_VERSION
        assert data["catalogue_id"] == _VALID_UUID
        assert data["packages"]["a/b"]["origin"]["type"] == "embedded"

        # Original registry.json renamed to *.bak-v0.4.<ms>
        assert not legacy.exists()
        backups = [p for p in os.listdir(str(tmp_path)) if p.startswith("registry.json.bak-v0.4.")]
        assert len(backups) == 1

    def test_no_op_on_already_migrated_catalogue(self, tmp_path):
        catalogue = tmp_path / CATALOGUE_FILENAME
        catalogue.write_text(json.dumps({
            "schema_version": CATALOGUE_SCHEMA_VERSION,
            "catalogue_id": _VALID_UUID,
            "packages": {},
        }), encoding="utf-8")
        out_path = migrate_local_registry_file_to_catalogue(str(catalogue))
        # Already migrated — function returns the same path, no backup.
        assert out_path == str(catalogue)
        backups = [p for p in os.listdir(str(tmp_path)) if "bak" in p]
        assert backups == []

    def test_missing_file_returns_empty(self, tmp_path):
        out_path = migrate_local_registry_file_to_catalogue(
            str(tmp_path / "nonexistent.json")
        )
        assert out_path == ""
