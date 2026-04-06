"""Tests for the icon cache LRU eviction helper."""

import os
import time

import pytest

from carton.core.icon_cache import enforce_size_limit


def _write(path, size):
    """Write a file of exactly ``size`` bytes."""
    with open(path, "wb") as f:
        f.write(b"x" * size)


def _age(path, seconds_ago):
    """Backdate a file's atime/mtime to simulate staleness."""
    t = time.time() - seconds_ago
    os.utime(path, (t, t))


class TestEnforceSizeLimit:
    def test_noop_when_under_limit(self, tmp_path):
        _write(tmp_path / "a.png", 100)
        _write(tmp_path / "b.png", 100)
        removed = enforce_size_limit(str(tmp_path), max_bytes=1000)
        assert removed == 0
        assert (tmp_path / "a.png").exists()
        assert (tmp_path / "b.png").exists()

    def test_missing_directory_is_noop(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        assert enforce_size_limit(str(missing)) == 0

    def test_evicts_oldest_first(self, tmp_path):
        _write(tmp_path / "old.png", 500)
        _write(tmp_path / "new.png", 500)
        _age(tmp_path / "old.png", 3600)   # 1h old
        _age(tmp_path / "new.png", 10)     # recent
        removed = enforce_size_limit(str(tmp_path), max_bytes=600)
        assert removed == 1
        assert not (tmp_path / "old.png").exists()
        assert (tmp_path / "new.png").exists()

    def test_keeps_evicting_until_under_limit(self, tmp_path):
        for i, age in enumerate([3000, 2000, 1000, 10]):
            p = tmp_path / "f{}.png".format(i)
            _write(p, 400)
            _age(p, age)
        # 1600 bytes total, cap at 500 → must evict the 3 oldest
        removed = enforce_size_limit(str(tmp_path), max_bytes=500)
        assert removed == 3
        assert (tmp_path / "f3.png").exists()
        for i in range(3):
            assert not (tmp_path / "f{}.png".format(i)).exists()

    def test_ignores_subdirectories(self, tmp_path):
        sub = tmp_path / "nested"
        sub.mkdir()
        _write(sub / "inner.png", 9999)
        _write(tmp_path / "top.png", 100)
        removed = enforce_size_limit(str(tmp_path), max_bytes=50)
        # Should target only top-level files, not recurse
        assert removed == 1
        assert not (tmp_path / "top.png").exists()
        assert (sub / "inner.png").exists()
