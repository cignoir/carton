"""Tests for the Local origin.

Covers path resolution (file vs directory), manifest parsing, version
enumeration, pinned/unpinned detection, relative artifact resolution
against the manifest directory, memoisation, and the ``from_dict`` /
``to_dict`` round trip.
"""

import json
import os

import pytest

from carton.core.origins import LocalOrigin, OriginError


def _write_manifest(dir_path, body):
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, "package.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f)
    return path


class TestConstruction:
    def test_empty_path_rejected(self):
        with pytest.raises(OriginError, match="non-empty 'path'"):
            LocalOrigin("")

    def test_from_dict_round_trip(self):
        origin = LocalOrigin.from_dict({"type": "local", "path": "/some/tool"})
        assert origin.to_dict() == {"type": "local", "path": "/some/tool"}

    def test_from_dict_wrong_type_rejected(self):
        with pytest.raises(OriginError, match="expected local origin"):
            LocalOrigin.from_dict({"type": "url", "url": "http://x"})


class TestPathResolution:
    def test_directory_path_resolves_to_manifest_inside(self, tmp_path):
        _write_manifest(str(tmp_path), {"version": "1.0.0"})
        versions = LocalOrigin(str(tmp_path)).list_versions()
        assert "1.0.0" in versions

    def test_file_path_accepted_directly(self, tmp_path):
        manifest = _write_manifest(str(tmp_path), {"version": "2.0.0"})
        versions = LocalOrigin(manifest).list_versions()
        assert "2.0.0" in versions

    def test_missing_directory_yields_empty(self, tmp_path):
        missing = tmp_path / "nope"
        assert LocalOrigin(str(missing)).list_versions() == {}

    def test_directory_without_manifest_yields_empty(self, tmp_path):
        # Directory exists but has no package.json — "moved / stale".
        (tmp_path / "empty").mkdir()
        assert LocalOrigin(str(tmp_path / "empty")).list_versions() == {}

    def test_expanduser_applied(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
        _write_manifest(str(tmp_path / "tool"), {"version": "1.0.0"})
        versions = LocalOrigin("~/tool").list_versions()
        assert "1.0.0" in versions


class TestVersionListing:
    def test_single_row_from_package_json(self, tmp_path):
        _write_manifest(str(tmp_path), {
            "version": "1.2.3",
            "maya_versions": ["2024", "2025"],
            "released_at": "2026-04-01T00:00:00Z",
            "changelog": "first release",
        })
        meta = LocalOrigin(str(tmp_path)).list_versions()["1.2.3"]
        assert meta.version == "1.2.3"
        assert meta.maya_versions == ["2024", "2025"]
        assert meta.released_at == "2026-04-01T00:00:00Z"
        assert meta.changelog == "first release"

    def test_missing_version_yields_empty(self, tmp_path):
        _write_manifest(str(tmp_path), {"name": "tool"})
        assert LocalOrigin(str(tmp_path)).list_versions() == {}

    def test_invalid_json_yields_empty(self, tmp_path):
        os.makedirs(str(tmp_path), exist_ok=True)
        with open(os.path.join(str(tmp_path), "package.json"), "w") as f:
            f.write("not valid json{")
        assert LocalOrigin(str(tmp_path)).list_versions() == {}

    def test_result_is_memoised(self, tmp_path):
        """Mutating package.json after first read doesn't change the
        origin's view — the origin holds its first snapshot for the
        session (matches UrlOrigin semantics)."""
        _write_manifest(str(tmp_path), {"version": "1.0.0"})
        origin = LocalOrigin(str(tmp_path))
        assert "1.0.0" in origin.list_versions()

        # Rewrite with a different version
        _write_manifest(str(tmp_path), {"version": "2.0.0"})
        assert list(origin.list_versions().keys()) == ["1.0.0"]  # stale


class TestArtifactResolution:
    def test_relative_artifact_resolves_against_manifest_dir(self, tmp_path):
        _write_manifest(str(tmp_path), {
            "version": "1.0.0",
            "download_url": "tool-1.0.0.zip",
            "sha256": "a" * 64,
        })
        art = LocalOrigin(str(tmp_path)).get_artifact("1.0.0")
        expected = os.path.normpath(os.path.join(str(tmp_path), "tool-1.0.0.zip"))
        assert art.url == expected
        assert art.is_pinned is True

    def test_absolute_artifact_passes_through(self, tmp_path):
        abs_artifact = os.path.normpath(str(tmp_path / "dist" / "x.zip"))
        _write_manifest(str(tmp_path), {
            "version": "1.0.0",
            "download_url": abs_artifact,
        })
        art = LocalOrigin(str(tmp_path)).get_artifact("1.0.0")
        assert art.url == abs_artifact

    def test_unpinned_when_sha256_missing(self, tmp_path):
        _write_manifest(str(tmp_path), {
            "version": "1.0.0",
            "download_url": "x.zip",
        })
        art = LocalOrigin(str(tmp_path)).get_artifact("1.0.0")
        assert art.is_pinned is False
        assert art.sha256 == ""

    def test_unknown_version_raises(self, tmp_path):
        _write_manifest(str(tmp_path), {
            "version": "1.0.0",
            "download_url": "x.zip",
        })
        with pytest.raises(OriginError, match="has no version"):
            LocalOrigin(str(tmp_path)).get_artifact("9.9.9")

    def test_missing_download_url_raises(self, tmp_path):
        _write_manifest(str(tmp_path), {"version": "1.0.0"})
        with pytest.raises(OriginError, match="missing download_url"):
            LocalOrigin(str(tmp_path)).get_artifact("1.0.0")

    def test_file_path_relative_artifact_resolves_against_parent(self, tmp_path):
        """When the origin was constructed with the file path (not the
        directory), relative artifacts still resolve against the
        manifest's parent directory."""
        manifest = _write_manifest(str(tmp_path / "dist"), {
            "version": "1.0.0",
            "download_url": "x.zip",
        })
        art = LocalOrigin(manifest).get_artifact("1.0.0")
        expected = os.path.normpath(os.path.join(str(tmp_path / "dist"), "x.zip"))
        assert art.url == expected
