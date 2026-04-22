"""Tests for the URL origin.

HTTP fetches are stubbed via monkeypatch so no live network I/O is
performed. The tests cover: manifest parsing, version enumeration,
pinned/unpinned detection, relative artifact URL resolution, memoised
failure, and the ``from_dict`` / ``to_dict`` round trip.
"""

import json
import io

import pytest

from carton.compat_urllib import URLError
from carton.core.origins import UrlOrigin, OriginError
from carton.core.origins import url_origin as url_module


_PKGJSON_URL = "https://example.com/tool/package.json"


def _response(body_dict):
    """Fake urlopen response: .read() returns UTF-8 bytes of JSON."""
    class _Resp:
        def read(self_inner):
            return json.dumps(body_dict).encode("utf-8")
    return _Resp()


@pytest.fixture
def fetch(monkeypatch):
    """Stub ``urlopen`` with a controllable dict state.

    The fixture returns a dict the tests can mutate before invoking the
    origin; setting state["error"] to an exception raises it instead of
    returning JSON (simulates network failure / 404).
    """
    state = {"body": None, "error": None}

    def _fake_urlopen(req, timeout=10):
        if state["error"] is not None:
            raise state["error"]
        return _response(state["body"])

    monkeypatch.setattr(url_module, "urlopen", _fake_urlopen)
    return state


class TestConstruction:
    def test_absolute_url_accepted(self):
        origin = UrlOrigin(_PKGJSON_URL)
        assert origin.url == _PKGJSON_URL

    def test_empty_url_rejected(self):
        with pytest.raises(OriginError, match="absolute http"):
            UrlOrigin("")

    def test_relative_url_rejected(self):
        with pytest.raises(OriginError, match="absolute http"):
            UrlOrigin("/tool/package.json")

    def test_from_dict_round_trip(self):
        origin = UrlOrigin.from_dict({"type": "url", "url": _PKGJSON_URL})
        assert origin.to_dict() == {"type": "url", "url": _PKGJSON_URL}

    def test_from_dict_wrong_type_rejected(self):
        with pytest.raises(OriginError, match="expected url origin"):
            UrlOrigin.from_dict({"type": "github", "repo": "a/b"})


class TestVersionListing:
    def test_single_row_from_package_json(self, fetch):
        fetch["body"] = {
            "version": "1.2.0",
            "maya_versions": ["2024", "2025"],
        }
        origin = UrlOrigin(_PKGJSON_URL)
        versions = origin.list_versions()
        assert list(versions.keys()) == ["1.2.0"]
        meta = versions["1.2.0"]
        assert meta.version == "1.2.0"
        assert meta.maya_versions == ["2024", "2025"]

    def test_missing_version_yields_empty(self, fetch):
        fetch["body"] = {"name": "tool"}  # No version field
        assert UrlOrigin(_PKGJSON_URL).list_versions() == {}

    def test_fetch_failure_yields_empty(self, fetch):
        fetch["error"] = URLError("connection refused")
        assert UrlOrigin(_PKGJSON_URL).list_versions() == {}

    def test_result_is_memoised(self, fetch):
        """Repeat list_versions / get_artifact calls must not re-fetch —
        the origin memoises the first response so catalogue rebuilds
        don't thrash the network."""
        call_count = {"n": 0}

        def _fake_urlopen(req, timeout=10):
            call_count["n"] += 1
            return _response({
                "version": "1.0.0",
                "download_url": "https://example.com/x.zip",
            })

        import carton.core.origins.url_origin as mod
        original = mod.urlopen
        mod.urlopen = _fake_urlopen
        try:
            origin = UrlOrigin(_PKGJSON_URL)
            origin.list_versions()
            origin.list_versions()
            origin.get_artifact("1.0.0")
        finally:
            mod.urlopen = original
        assert call_count["n"] == 1

    def test_failure_is_memoised_not_retried(self, fetch):
        """After a network error the origin records empty and does NOT
        retry in the same session — avoids n² bad requests while a
        remote host is down."""
        fetch["error"] = URLError("connection refused")
        origin = UrlOrigin(_PKGJSON_URL)
        assert origin.list_versions() == {}
        # Now drop the error; the origin should still return empty
        # because the negative result is memoised.
        fetch["error"] = None
        fetch["body"] = {"version": "1.0.0"}
        assert origin.list_versions() == {}


class TestArtifactResolution:
    def test_absolute_download_url_pinned(self, fetch):
        fetch["body"] = {
            "version": "1.0.0",
            "download_url": "https://cdn.example.com/tool-1.0.0.zip",
            "sha256": "a" * 64,
            "size_bytes": 123,
        }
        art = UrlOrigin(_PKGJSON_URL).get_artifact("1.0.0")
        assert art.url == "https://cdn.example.com/tool-1.0.0.zip"
        assert art.sha256 == "a" * 64
        assert art.is_pinned is True
        assert art.size_bytes == 123

    def test_relative_download_url_resolved_against_manifest(self, fetch):
        fetch["body"] = {
            "version": "1.0.0",
            "download_url": "tool-1.0.0.zip",
            "sha256": "b" * 64,
        }
        art = UrlOrigin(_PKGJSON_URL).get_artifact("1.0.0")
        # manifest is at .../tool/package.json, so relative resolves to
        # .../tool/tool-1.0.0.zip.
        assert art.url == "https://example.com/tool/tool-1.0.0.zip"

    def test_unpinned_when_sha256_missing(self, fetch):
        fetch["body"] = {
            "version": "1.0.0",
            "download_url": "https://example.com/x.zip",
        }
        art = UrlOrigin(_PKGJSON_URL).get_artifact("1.0.0")
        assert art.is_pinned is False
        assert art.sha256 == ""

    def test_unpinned_when_sha256_wrong_length(self, fetch):
        fetch["body"] = {
            "version": "1.0.0",
            "download_url": "https://example.com/x.zip",
            "sha256": "short",  # Not 64 chars — not a valid hash
        }
        art = UrlOrigin(_PKGJSON_URL).get_artifact("1.0.0")
        assert art.is_pinned is False

    def test_unknown_version_raises(self, fetch):
        fetch["body"] = {
            "version": "1.0.0",
            "download_url": "https://example.com/x.zip",
        }
        with pytest.raises(OriginError, match="has no version"):
            UrlOrigin(_PKGJSON_URL).get_artifact("9.9.9")

    def test_missing_download_url_raises(self, fetch):
        fetch["body"] = {"version": "1.0.0"}
        with pytest.raises(OriginError, match="missing download_url"):
            UrlOrigin(_PKGJSON_URL).get_artifact("1.0.0")

    def test_sha256_lowercased(self, fetch):
        fetch["body"] = {
            "version": "1.0.0",
            "download_url": "https://example.com/x.zip",
            "sha256": "A" * 64,
        }
        art = UrlOrigin(_PKGJSON_URL).get_artifact("1.0.0")
        assert art.sha256 == "a" * 64
