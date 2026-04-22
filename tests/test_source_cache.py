"""Tests for the source cache (API responses + TOFU sha256)."""

import os
import time

import pytest

from carton.core.source_cache import SourceCache


@pytest.fixture
def cache(tmp_path):
    return SourceCache(cache_dir=str(tmp_path), api_ttl_seconds=2)


class TestApiCache:
    def test_miss_returns_none(self, cache):
        body, etag = cache.read_api("https://example.com/foo")
        assert body is None
        assert etag == ""

    def test_round_trip(self, cache):
        cache.write_api("https://example.com/foo", {"a": 1}, etag="abc")
        body, etag = cache.read_api("https://example.com/foo")
        assert body == {"a": 1}
        assert etag == "abc"

    def test_expiry_returns_none_but_keeps_etag(self, tmp_path):
        c = SourceCache(cache_dir=str(tmp_path), api_ttl_seconds=0)
        c.write_api("https://example.com/foo", {"a": 1}, etag="abc")
        time.sleep(0.05)
        body, etag = c.read_api("https://example.com/foo")
        assert body is None
        # ETag still available so the caller can do a 304 conditional GET.
        assert etag == "abc"

    def test_keys_with_special_chars(self, cache):
        url = "https://api.github.com/repos/owner/repo?per_page=100"
        cache.write_api(url, [1, 2, 3], etag="x")
        body, _ = cache.read_api(url)
        assert body == [1, 2, 3]


class TestPinnedSha256:
    def test_miss_returns_empty(self, cache):
        assert cache.read_pinned_sha256("https://example.com/x.zip") == ""

    def test_round_trip(self, cache):
        cache.write_pinned_sha256("https://example.com/x.zip", "A" * 64)
        # Stored lowercase.
        assert cache.read_pinned_sha256("https://example.com/x.zip") == "a" * 64

    def test_empty_sha_is_no_op(self, cache):
        cache.write_pinned_sha256("https://example.com/x.zip", "")
        assert cache.read_pinned_sha256("https://example.com/x.zip") == ""

    def test_forget_removes_pin(self, cache):
        cache.write_pinned_sha256("https://example.com/x.zip", "a" * 64)
        assert cache.forget_pinned_sha256("https://example.com/x.zip") is True
        assert cache.read_pinned_sha256("https://example.com/x.zip") == ""

    def test_forget_missing_is_false(self, cache):
        assert cache.forget_pinned_sha256("https://example.com/none.zip") is False

    def test_pinned_sha_persists_across_instances(self, tmp_path):
        c1 = SourceCache(cache_dir=str(tmp_path))
        c1.write_pinned_sha256("https://example.com/y.zip", "c" * 64)
        c2 = SourceCache(cache_dir=str(tmp_path))
        assert c2.read_pinned_sha256("https://example.com/y.zip") == "c" * 64
