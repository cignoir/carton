"""Tests for the embedded origin (catalogue-hosted artifacts)."""

import os

import pytest

from carton.core.origins import EmbeddedOrigin, OriginError, origin_from_dict


_VERSIONS = {
    "1.0.0": {
        "maya_versions": ["2024", "2025"],
        "download_url": "packages/test/tool/1.0.0/tool-1.0.0.zip",
        "sha256": "a" * 64,
        "size_bytes": 100,
        "released_at": "2026-03-01T00:00:00Z",
        "changelog": "first",
    },
    "2.0.0": {
        "maya_versions": ["2026", "2027"],
        "download_url": "packages/test/tool/2.0.0/tool-2.0.0.zip",
        "sha256": "b" * 64,
        "size_bytes": 200,
        "released_at": "2026-04-01T00:00:00Z",
        "changelog": "second",
    },
}


class TestEmbeddedOrigin:
    def test_factory_dispatches_to_embedded(self):
        origin = origin_from_dict(
            {"type": "embedded", "versions": _VERSIONS, "latest_version": "2.0.0"},
            base_dir="/tmp/cat",
        )
        assert isinstance(origin, EmbeddedOrigin)

    def test_factory_rejects_unknown_type(self):
        with pytest.raises(OriginError):
            origin_from_dict({"type": "novel"}, base_dir="")

    def test_list_versions_yields_meta(self):
        origin = EmbeddedOrigin(versions=_VERSIONS, latest_version="2.0.0",
                                base_dir="/tmp/cat")
        out = origin.list_versions()
        assert set(out.keys()) == {"1.0.0", "2.0.0"}
        assert out["1.0.0"].maya_versions == ["2024", "2025"]
        assert out["2.0.0"].changelog == "second"

    def test_latest_version_uses_explicit_value(self):
        origin = EmbeddedOrigin(versions=_VERSIONS, latest_version="1.0.0",
                                base_dir="")
        assert origin.latest_version() == "1.0.0"

    def test_latest_version_falls_back_to_lex_max(self):
        origin = EmbeddedOrigin(versions=_VERSIONS, base_dir="")
        assert origin.latest_version() == "2.0.0"

    def test_get_artifact_resolves_relative_local_path(self, tmp_path):
        origin = EmbeddedOrigin(versions=_VERSIONS, base_dir=str(tmp_path))
        ref = origin.get_artifact("1.0.0")
        expected = os.path.normpath(
            os.path.join(str(tmp_path), "packages/test/tool/1.0.0/tool-1.0.0.zip")
        )
        assert ref.url == expected
        assert ref.sha256 == "a" * 64
        assert ref.size_bytes == 100
        assert ref.is_pinned is True

    def test_get_artifact_resolves_relative_remote_path(self):
        origin = EmbeddedOrigin(
            versions=_VERSIONS,
            base_dir="https://example.com/cat/",
        )
        ref = origin.get_artifact("2.0.0")
        assert ref.url == (
            "https://example.com/cat/packages/test/tool/2.0.0/tool-2.0.0.zip"
        )
        assert ref.sha256 == "b" * 64

    def test_get_artifact_keeps_absolute_url(self):
        absurl = "https://cdn.example.com/foo.zip"
        versions = {"1.0.0": dict(_VERSIONS["1.0.0"], download_url=absurl)}
        origin = EmbeddedOrigin(versions=versions, base_dir="/tmp/cat")
        ref = origin.get_artifact("1.0.0")
        assert ref.url == absurl

    def test_get_artifact_unknown_version_raises(self):
        origin = EmbeddedOrigin(versions=_VERSIONS, base_dir="")
        with pytest.raises(OriginError):
            origin.get_artifact("9.9.9")

    def test_get_artifact_missing_url_raises(self):
        origin = EmbeddedOrigin(
            versions={"1.0.0": {"maya_versions": ["2024"]}},
            base_dir="/tmp/cat",
        )
        with pytest.raises(OriginError):
            origin.get_artifact("1.0.0")

    def test_unpinned_when_sha256_missing(self):
        versions = {"1.0.0": dict(_VERSIONS["1.0.0"])}
        del versions["1.0.0"]["sha256"]
        origin = EmbeddedOrigin(versions=versions, base_dir="/tmp/cat")
        ref = origin.get_artifact("1.0.0")
        assert ref.sha256 == ""
        assert ref.is_pinned is False

    def test_to_dict_round_trip(self):
        origin = EmbeddedOrigin(versions=_VERSIONS, latest_version="2.0.0",
                                base_dir="/tmp/cat")
        d = origin.to_dict()
        assert d["type"] == "embedded"
        assert d["latest_version"] == "2.0.0"
        assert "1.0.0" in d["versions"]
