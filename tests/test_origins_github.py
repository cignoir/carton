"""Tests for the GitHub origin.

Network calls are stubbed via monkeypatch on the github_api module —
no live HTTP is performed.
"""

import pytest

from carton.core import github_api
from carton.core.origins import GithubOrigin, OriginError


def _release(tag, assets=None, body="", published_at="", draft=False):
    return {
        "tag_name": tag,
        "draft": draft,
        "body": body,
        "published_at": published_at,
        "assets": assets or [],
    }


def _asset(name, url="", size=0):
    return {
        "name": name,
        "browser_download_url": url or "https://example.com/{}".format(name),
        "size": size,
    }


@pytest.fixture
def stub_releases(monkeypatch):
    """Replace github_api.list_releases with a controllable fake."""
    state = {"releases": [], "tags": [], "default_branch": "main"}

    def _list_releases(repo, cache=None):
        return state["releases"]

    def _list_tags(repo, cache=None):
        return state["tags"]

    def _default_branch(repo, cache=None):
        return state["default_branch"]

    def _fetch_raw_text(url, timeout=15):
        return state.get("sha256sums_body", "")

    monkeypatch.setattr(github_api, "list_releases", _list_releases)
    monkeypatch.setattr(github_api, "list_tags", _list_tags)
    monkeypatch.setattr(github_api, "get_default_branch", _default_branch)
    monkeypatch.setattr(github_api, "fetch_raw_text", _fetch_raw_text)
    return state


class TestGithubOriginVersionListing:
    def test_releases_become_versions(self, stub_releases):
        stub_releases["releases"] = [
            _release("v1.0.0", published_at="2026-01-01T00:00:00Z"),
            _release("v2.0.0", published_at="2026-02-01T00:00:00Z"),
        ]
        origin = GithubOrigin(repo="user/tool")
        versions = origin.list_versions()
        assert set(versions.keys()) == {"1.0.0", "2.0.0"}
        assert versions["1.0.0"].released_at == "2026-01-01T00:00:00Z"

    def test_drafts_are_skipped(self, stub_releases):
        stub_releases["releases"] = [
            _release("v1.0.0"),
            _release("v2.0.0", draft=True),
        ]
        origin = GithubOrigin(repo="user/tool")
        assert set(origin.list_versions().keys()) == {"1.0.0"}

    def test_tags_used_as_fallback(self, stub_releases):
        stub_releases["releases"] = []
        stub_releases["tags"] = [{"name": "v0.1.0"}, {"name": "v0.2.0"}]
        origin = GithubOrigin(repo="user/tool")
        assert set(origin.list_versions().keys()) == {"0.1.0", "0.2.0"}

    def test_explicit_ref_yields_single_version(self, stub_releases):
        origin = GithubOrigin(repo="user/tool", ref="feature-xyz")
        versions = origin.list_versions()
        assert list(versions.keys()) == ["feature-xyz"]


class TestGithubOriginArtifactResolution:
    def test_release_asset_pinned_with_sha256sums(self, stub_releases):
        stub_releases["releases"] = [
            _release("v1.0.0", assets=[
                _asset("rigger-1.0.0.zip", url="https://example.com/rigger-1.0.0.zip", size=42),
                _asset("SHA256SUMS", url="https://example.com/SHA256SUMS"),
            ]),
        ]
        stub_releases["sha256sums_body"] = (
            ("a" * 64) + "  rigger-1.0.0.zip\n"
        )
        origin = GithubOrigin(repo="user/rigger")
        ref = origin.get_artifact("1.0.0", package_name="rigger")
        assert ref.url == "https://example.com/rigger-1.0.0.zip"
        assert ref.sha256 == "a" * 64
        assert ref.is_pinned is True
        assert ref.size_bytes == 42

    def test_release_asset_unpinned_without_sha256sums(self, stub_releases):
        stub_releases["releases"] = [
            _release("v1.0.0", assets=[
                _asset("rigger-1.0.0.zip", url="https://example.com/rigger-1.0.0.zip"),
            ]),
        ]
        origin = GithubOrigin(repo="user/rigger")
        ref = origin.get_artifact("1.0.0", package_name="rigger")
        assert ref.url == "https://example.com/rigger-1.0.0.zip"
        assert ref.sha256 == ""
        assert ref.is_pinned is False

    def test_falls_back_to_auto_archive_when_no_asset(self, stub_releases):
        stub_releases["releases"] = [_release("v1.0.0")]
        origin = GithubOrigin(repo="user/rigger")
        ref = origin.get_artifact("1.0.0", package_name="rigger")
        assert "archive/refs/tags/v1.0.0.zip" in ref.url
        assert ref.is_pinned is False

    def test_head_uses_default_branch_archive(self, stub_releases):
        stub_releases["releases"] = []
        stub_releases["tags"] = []
        stub_releases["default_branch"] = "trunk"
        origin = GithubOrigin(repo="user/rigger")
        ref = origin.get_artifact("HEAD")
        assert "archive/refs/heads/trunk.zip" in ref.url

    def test_unknown_version_raises(self, stub_releases):
        stub_releases["releases"] = [_release("v1.0.0")]
        origin = GithubOrigin(repo="user/rigger")
        with pytest.raises(OriginError):
            origin.get_artifact("9.9.9")

    def test_asset_match_without_package_name_uses_suffix(self, stub_releases):
        stub_releases["releases"] = [
            _release("v1.0.0", assets=[
                _asset("anything-1.0.0.zip", url="https://example.com/x.zip"),
            ]),
        ]
        origin = GithubOrigin(repo="user/rigger")
        ref = origin.get_artifact("1.0.0")  # no package_name hint
        assert ref.url == "https://example.com/x.zip"


class TestGithubOriginValidation:
    def test_invalid_repo_form(self):
        with pytest.raises(OriginError):
            GithubOrigin(repo="not-a-slug")

    def test_from_dict_round_trip(self):
        d = {"type": "github", "repo": "user/tool", "ref": "main"}
        origin = GithubOrigin.from_dict(d)
        out = origin.to_dict()
        assert out["type"] == "github"
        assert out["repo"] == "user/tool"
        assert out["ref"] == "main"

    def test_from_dict_rejects_wrong_type(self):
        with pytest.raises(OriginError):
            GithubOrigin.from_dict({"type": "embedded"})
