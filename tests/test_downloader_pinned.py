"""Tests for ``Downloader.download_artifact`` — v5.0 pinned/unpinned policy.

Covers the Step 2 decision matrix (cross-referenced in ``downloader.py``):

* pinned ref + matching sha → success, no TOFU write
* pinned ref + mismatched sha → DownloadError (from underlying verify)
* unpinned ref + strict_verify=True → DownloadError, network never touched
* unpinned ref + no cache → downloads without verification, no pin recorded
* unpinned ref + cache first fetch → downloads, sha256 written to cache (TOFU)
* unpinned ref + cache with matching prior pin → succeeds, pin unchanged
* unpinned ref + cache with drifted prior pin → DownloadError
* missing URL in ArtifactRef → DownloadError (fail fast)

All tests use local file paths so no HTTP mocking is needed — the
underlying :meth:`Downloader.download` picks the ``_copy_local`` branch
for non-URL paths, and the pinned/unpinned logic runs identically either
way.
"""

import hashlib
import os

import pytest

from carton.core.downloader import Downloader, DownloadError
from carton.core.origins import ArtifactRef
from carton.core.source_cache import SourceCache


class _StubConfig(object):
    def __init__(self, strict_verify=False):
        self.strict_verify = bool(strict_verify)


@pytest.fixture
def payload(tmp_path):
    """Write a fixture file on disk and return (path, sha256)."""
    src = tmp_path / "src.zip"
    data = b"payload-bytes-for-hashing"
    src.write_bytes(data)
    return str(src), hashlib.sha256(data).hexdigest()


@pytest.fixture
def dest(tmp_path):
    return str(tmp_path / "out" / "dest.zip")


@pytest.fixture
def cache(tmp_path):
    return SourceCache(cache_dir=str(tmp_path / "cache"))


class TestPinnedRef:
    def test_matching_sha_downloads(self, payload, dest):
        src, sha = payload
        ref = ArtifactRef(url=src, sha256=sha, size_bytes=0, is_pinned=True,
                          source_label="embedded")
        Downloader(_StubConfig()).download_artifact(ref, dest)
        assert os.path.exists(dest)

    def test_mismatched_sha_raises(self, payload, dest):
        src, _ = payload
        ref = ArtifactRef(url=src, sha256="f" * 64, is_pinned=True)
        with pytest.raises(DownloadError, match="SHA256 mismatch"):
            Downloader(_StubConfig()).download_artifact(ref, dest)
        # Copy was staged then removed after the hash mismatch; the final
        # dest must not be left behind.
        assert not os.path.exists(dest)

    def test_pinned_does_not_write_to_cache(self, payload, dest, cache):
        src, sha = payload
        ref = ArtifactRef(url=src, sha256=sha, is_pinned=True)
        Downloader(_StubConfig()).download_artifact(ref, dest, cache=cache)
        # Pinned refs already carry authoritative sha; no TOFU needed.
        assert cache.read_pinned_sha256(src) == ""


class TestStrictVerifyGate:
    def test_unpinned_rejected_when_strict(self, payload, dest):
        src, _ = payload
        ref = ArtifactRef(url=src, is_pinned=False,
                          source_label="github auto archive")
        with pytest.raises(DownloadError, match="unpinned source rejected"):
            Downloader(_StubConfig(strict_verify=True)).download_artifact(ref, dest)
        # Fail fast: no file should have been written.
        assert not os.path.exists(dest)

    def test_empty_url_raises_fast(self, dest):
        ref = ArtifactRef(url="", is_pinned=True)
        with pytest.raises(DownloadError, match="no URL"):
            Downloader(_StubConfig()).download_artifact(ref, dest)


class TestUnpinnedTofu:
    def test_no_cache_downloads_without_verification(self, payload, dest):
        src, _ = payload
        ref = ArtifactRef(url=src, is_pinned=False)
        # cache=None disables TOFU entirely — this is the back-compat
        # escape hatch for callers that don't have a cache available.
        Downloader(_StubConfig()).download_artifact(ref, dest, cache=None)
        assert os.path.exists(dest)

    def test_first_fetch_records_sha_in_cache(self, payload, dest, cache):
        src, sha = payload
        ref = ArtifactRef(url=src, is_pinned=False)
        Downloader(_StubConfig()).download_artifact(ref, dest, cache=cache)
        assert cache.read_pinned_sha256(src) == sha

    def test_subsequent_fetch_verifies_against_cached_pin(
        self, payload, dest, cache
    ):
        src, sha = payload
        # Pre-seed cache to simulate "second fetch" — artifact matches the
        # prior pin so the download should verify cleanly.
        cache.write_pinned_sha256(src, sha)
        ref = ArtifactRef(url=src, is_pinned=False)
        Downloader(_StubConfig()).download_artifact(ref, dest, cache=cache)
        # Pin unchanged — TOFU is a first-fetch-only action.
        assert cache.read_pinned_sha256(src) == sha

    def test_subsequent_fetch_rejects_when_content_drifts(
        self, payload, dest, cache
    ):
        src, _ = payload
        # Cache says we previously saw a different hash for this URL.
        # Current file sha doesn't match → verify fails → DownloadError.
        cache.write_pinned_sha256(src, "0" * 64)
        ref = ArtifactRef(url=src, is_pinned=False)
        with pytest.raises(DownloadError, match="SHA256 mismatch"):
            Downloader(_StubConfig()).download_artifact(ref, dest, cache=cache)

    def test_strict_verify_off_allows_unpinned_without_cache(
        self, payload, dest
    ):
        """strict_verify=False is the Phase-A default for users who haven't
        opted into paranoid mode — unpinned sources must still work."""
        src, _ = payload
        ref = ArtifactRef(url=src, is_pinned=False)
        Downloader(_StubConfig(strict_verify=False)).download_artifact(
            ref, dest, cache=None,
        )
        assert os.path.exists(dest)
