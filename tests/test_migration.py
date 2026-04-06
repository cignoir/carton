"""Tests for the registry migration tool (UUID keys -> namespace/name keys)."""

import json
import os
import tempfile
import zipfile

import pytest

from carton.core.migration import migrate_registry, MigrationError


_UUID_A = "11111111-2222-3333-4444-555555555555"
_UUID_B = "66666666-7777-8888-9999-aaaaaaaaaaaa"


def _build_legacy_registry(base_dir):
    """Create a v2-style registry with two UUID-keyed packages."""
    pkg_a_zip_dir = os.path.join(base_dir, "packages", _UUID_A, "1.0.0")
    os.makedirs(pkg_a_zip_dir, exist_ok=True)
    pkg_a_zip = os.path.join(pkg_a_zip_dir, "rigger-1.0.0.zip")
    with zipfile.ZipFile(pkg_a_zip, "w") as zf:
        zf.writestr("rigger/__init__.py", "def show(): pass\n")
        zf.writestr("package.json", json.dumps({
            "id": _UUID_A,
            "name": "rigger",
            "display_name": "Rigger",
            "version": "1.0.0",
            "type": "python_package",
            "author": "alice",
            "entry_point": {"type": "python", "module": "rigger", "function": "show"},
        }))

    pkg_b_zip_dir = os.path.join(base_dir, "packages", _UUID_B, "0.5.0")
    os.makedirs(pkg_b_zip_dir, exist_ok=True)
    pkg_b_zip = os.path.join(pkg_b_zip_dir, "rename-0.5.0.zip")
    with zipfile.ZipFile(pkg_b_zip, "w") as zf:
        zf.writestr("rename.mel", "// mel")
        zf.writestr("package.json", json.dumps({
            "id": _UUID_B,
            "name": "rename",
            "display_name": "Rename",
            "version": "0.5.0",
            "type": "mel_script",
            "author": "bob",
            "entry_point": {"type": "mel", "script": "rename.mel", "procedure": "rename"},
        }))

    registry = {
        "schema_version": "2.0",
        "packages": {
            _UUID_A: {
                "name": "rigger",
                "display_name": "Rigger",
                "type": "python_package",
                "description": "",
                "author": "alice",
                "latest_version": "1.0.0",
                "versions": {
                    "1.0.0": {
                        "maya_versions": ["2024"],
                        "download_url": "packages/{}/1.0.0/rigger-1.0.0.zip".format(_UUID_A),
                        "sha256": "0" * 64,
                        "size_bytes": 100,
                        "released_at": "2024-01-01T00:00:00Z",
                    }
                },
            },
            _UUID_B: {
                "name": "rename",
                "display_name": "Rename",
                "type": "mel_script",
                "description": "",
                "author": "bob",
                "latest_version": "0.5.0",
                "versions": {
                    "0.5.0": {
                        "maya_versions": ["2024"],
                        "download_url": "packages/{}/0.5.0/rename-0.5.0.zip".format(_UUID_B),
                        "sha256": "0" * 64,
                        "size_bytes": 100,
                        "released_at": "2024-02-01T00:00:00Z",
                    }
                },
            },
        },
    }
    reg_path = os.path.join(base_dir, "registry.json")
    with open(reg_path, "w") as f:
        json.dump(registry, f)
    return reg_path


def test_migrate_rewrites_keys_and_zip_paths():
    with tempfile.TemporaryDirectory() as tmp:
        reg_path = _build_legacy_registry(tmp)
        result = migrate_registry(reg_path, "mystudio")
        assert result["migrated"] == 2

        with open(reg_path) as f:
            registry = json.load(f)

        assert registry["schema_version"] == "3.0"
        assert "mystudio/rigger" in registry["packages"]
        assert "mystudio/rename" in registry["packages"]
        assert _UUID_A not in registry["packages"]

        rigger = registry["packages"]["mystudio/rigger"]
        assert rigger["namespace"] == "mystudio"
        assert rigger["name"] == "rigger"
        assert rigger["first_published_by"] == "alice"
        assert rigger["versions"]["1.0.0"]["download_url"] == \
            "packages/mystudio/rigger/1.0.0/rigger-1.0.0.zip"

        new_zip = os.path.join(tmp, "packages", "mystudio", "rigger", "1.0.0", "rigger-1.0.0.zip")
        assert os.path.exists(new_zip)

        # Old uuid dir is gone
        assert not os.path.exists(os.path.join(tmp, "packages", _UUID_A))

        # Inner package.json is rewritten
        with zipfile.ZipFile(new_zip) as zf:
            inner = json.loads(zf.read("package.json").decode("utf-8"))
        assert inner["namespace"] == "mystudio"
        assert "id" not in inner


def test_migrate_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        reg_path = _build_legacy_registry(tmp)
        before = os.path.getmtime(reg_path)
        result = migrate_registry(reg_path, "mystudio", dry_run=True)
        assert result.get("dry_run") is True
        assert os.path.getmtime(reg_path) == before
        assert os.path.exists(os.path.join(tmp, "packages", _UUID_A))


def test_migrate_collision_aborts():
    """Two UUIDs with the same name -> single target key -> error."""
    with tempfile.TemporaryDirectory() as tmp:
        reg_path = _build_legacy_registry(tmp)
        with open(reg_path) as f:
            registry = json.load(f)
        # Force a collision: rename UUID_B's name to "rigger"
        registry["packages"][_UUID_B]["name"] = "rigger"
        with open(reg_path, "w") as f:
            json.dump(registry, f)

        with pytest.raises(MigrationError):
            migrate_registry(reg_path, "mystudio")
