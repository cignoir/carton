"""Tests for v0.3.x → v0.4.0 schema migrations."""

import json
import os
import tempfile

from carton.core.migrations import (
    INSTALLED_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
    migrate_installed_data,
    migrate_installed_file,
    migrate_local_registry_file,
    migrate_registry_data,
)


_VALID_UUID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


class TestMigrateInstalledData:
    def test_passthrough_when_already_v4(self):
        data = {
            "schema_version": INSTALLED_SCHEMA_VERSION,
            "packages": {"a/b": {"namespace": "a", "name": "b", "source": "registry"}},
        }
        out, was = migrate_installed_data(data)
        assert was is False
        assert out is data

    def test_published_becomes_registry(self):
        data = {
            "schema_version": "3.0",
            "packages": {
                "a/b": {
                    "namespace": "a", "name": "b", "version": "1.0.0",
                    "type": "python_package", "installed_at": "2026-01-01T00:00:00Z",
                    "source": "published",
                    "local_path": "/tmp/foo",
                    "path": "packages/a/b",
                },
            },
        }
        out, was = migrate_installed_data(data)
        assert was is True
        assert out["schema_version"] == INSTALLED_SCHEMA_VERSION
        entry = out["packages"]["a/b"]
        assert entry["source"] == "registry"
        assert entry["local_path"] == "/tmp/foo"

    def test_local_script_becomes_local(self):
        data = {
            "schema_version": "3.0",
            "packages": {
                "x": {
                    "name": "x", "version": "1.0.0", "type": "python_package",
                    "installed_at": "2026-01-01T00:00:00Z",
                    "source": "local_script",
                    "local_path": "/tmp/x",
                    "display_name": "X",
                    "entry_point": {"type": "python", "module": "x", "function": "show"},
                },
            },
        }
        out, was = migrate_installed_data(data)
        assert was is True
        entry = out["packages"]["x"]
        assert entry["source"] == "local"
        # My Tools entries keep their entry_point and display_name (SoT).
        assert entry["entry_point"]["module"] == "x"
        assert entry["display_name"] == "X"

    def test_registry_drops_entry_point_display_name_and_sha(self):
        data = {
            "schema_version": "3.0",
            "packages": {
                "a/b": {
                    "namespace": "a", "name": "b", "version": "1.0.0",
                    "type": "python_package", "installed_at": "2026-01-01T00:00:00Z",
                    "source": "registry",
                    "path": "packages/a/b",
                    "entry_point": {"type": "python", "module": "b", "function": "show"},
                    "display_name": "B",
                    "sha256": "deadbeef",
                },
            },
        }
        out, _ = migrate_installed_data(data)
        entry = out["packages"]["a/b"]
        assert "entry_point" not in entry
        assert "display_name" not in entry
        assert "sha256" not in entry

    def test_truly_unknown_source_with_path_becomes_registry(self):
        # ``"weird"`` isn't in any historical enum — coerce based on whether
        # the entry has bytes on disk. Path present → registry-installed.
        data = {
            "schema_version": "3.0",
            "packages": {
                "a/b": {
                    "namespace": "a", "name": "b", "version": "1.0.0",
                    "type": "python_package", "installed_at": "x",
                    "source": "weird", "path": "packages/a/b",
                },
            },
        }
        out, _ = migrate_installed_data(data)
        assert out["packages"]["a/b"]["source"] == "registry"

    def test_already_local_passes_through(self):
        """``source="local"`` is the new canonical enum — leave it alone."""
        data = {
            "schema_version": "3.0",
            "packages": {
                "x": {"name": "x", "source": "local", "local_path": "/tmp/x"},
            },
        }
        out, _ = migrate_installed_data(data)
        assert out["packages"]["x"]["source"] == "local"

    def test_idempotent_after_one_pass(self):
        data = {
            "schema_version": "3.0",
            "packages": {"x": {"name": "x", "source": "local_script"}},
        }
        once, _ = migrate_installed_data(data)
        twice, was2 = migrate_installed_data(once)
        assert was2 is False
        assert twice is once


class TestMigrateRegistryData:
    def test_passthrough_when_already_v4(self):
        data = {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "registry_id": _VALID_UUID,
            "packages": {},
        }
        out, was = migrate_registry_data(data)
        assert was is False
        assert out is data

    def test_v3_1_with_registry_id_only_bumps_version(self):
        data = {
            "schema_version": "3.1",
            "registry_id": _VALID_UUID,
            "packages": {},
        }
        out, was = migrate_registry_data(data)
        assert was is True
        assert out["schema_version"] == REGISTRY_SCHEMA_VERSION
        assert out["registry_id"] == _VALID_UUID

    def test_missing_registry_id_gets_stamped(self):
        data = {"schema_version": "3.0", "packages": {}}
        out, was = migrate_registry_data(data)
        assert was is True
        assert out["registry_id"]  # non-empty UUID
        assert out["schema_version"] == REGISTRY_SCHEMA_VERSION

    def test_stamp_id_false_keeps_id_empty(self):
        """Remote-only reads must not generate ephemeral UUIDs."""
        data = {"schema_version": "3.0", "packages": {}}
        out, _ = migrate_registry_data(data, stamp_id=False)
        assert out.get("registry_id", "") == ""
        assert out["schema_version"] == REGISTRY_SCHEMA_VERSION

    def test_legacy_icon_true_becomes_at_auto(self):
        data = {
            "schema_version": "3.1",
            "registry_id": _VALID_UUID,
            "packages": {
                "a/b": {"name": "b", "icon": True},
            },
        }
        out, was = migrate_registry_data(data)
        assert was is True
        assert out["packages"]["a/b"]["icon"] == "@auto"

    def test_legacy_icon_false_becomes_null(self):
        data = {
            "schema_version": "3.1",
            "registry_id": _VALID_UUID,
            "packages": {
                "a/b": {"name": "b", "icon": False},
            },
        }
        out, _ = migrate_registry_data(data)
        assert out["packages"]["a/b"]["icon"] is None


class TestFileMigrations:
    def test_installed_file_round_trip(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text(json.dumps({
            "schema_version": "3.0",
            "packages": {
                "a/b": {
                    "namespace": "a", "name": "b", "version": "1.0.0",
                    "type": "python_package", "installed_at": "x",
                    "source": "published", "local_path": "/tmp/foo",
                    "path": "packages/a/b", "sha256": "abc",
                },
            },
        }), encoding="utf-8")

        wrote = migrate_installed_file(str(path))
        assert wrote is True
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == INSTALLED_SCHEMA_VERSION
        assert data["packages"]["a/b"]["source"] == "registry"
        assert "sha256" not in data["packages"]["a/b"]
        # Backup left next to the original
        backups = [
            p for p in os.listdir(str(tmp_path))
            if p.startswith("installed.json.bak-")
        ]
        assert len(backups) == 1

    def test_installed_file_idempotent(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text(json.dumps({
            "schema_version": INSTALLED_SCHEMA_VERSION,
            "packages": {},
        }), encoding="utf-8")
        assert migrate_installed_file(str(path)) is False
        # No backup created when nothing was migrated
        backups = [
            p for p in os.listdir(str(tmp_path))
            if p.startswith("installed.json.bak-")
        ]
        assert backups == []

    def test_registry_file_round_trip(self, tmp_path):
        path = tmp_path / "registry.json"
        path.write_text(json.dumps({
            "schema_version": "3.0",
            "packages": {"a/b": {"name": "b", "icon": True}},
        }), encoding="utf-8")

        wrote = migrate_local_registry_file(str(path))
        assert wrote is True
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == REGISTRY_SCHEMA_VERSION
        assert data["registry_id"]
        assert data["packages"]["a/b"]["icon"] == "@auto"
