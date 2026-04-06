"""Tests for store_local_path / resolve_local_path."""

import os

import pytest

from carton.core.path_utils import resolve_local_path, store_local_path


class TestStoreLocalPath:
    def test_empty_is_passthrough(self):
        assert store_local_path("") == ""
        assert store_local_path(None) is None

    def test_collapses_home_directory(self, monkeypatch):
        fake_home = os.path.normpath("/home/alice")
        monkeypatch.setenv("HOME", fake_home)
        monkeypatch.setenv("USERPROFILE", fake_home)
        stored = store_local_path(os.path.join(fake_home, "tools", "rigger.py"))
        assert stored == "~/tools/rigger.py"

    def test_leaves_out_of_home_alone(self, monkeypatch):
        fake_home = os.path.normpath("/home/alice")
        monkeypatch.setenv("HOME", fake_home)
        monkeypatch.setenv("USERPROFILE", fake_home)
        outside = os.path.normpath("/opt/studio/tools/foo.py")
        assert store_local_path(outside) == outside

    def test_preserves_env_var_references(self):
        assert store_local_path("$STUDIO/tools/foo.py") == "$STUDIO/tools/foo.py"
        assert store_local_path("%STUDIO%\\tools\\foo.py") == "%STUDIO%\\tools\\foo.py"


class TestResolveLocalPath:
    def test_empty_is_passthrough(self):
        assert resolve_local_path("") == ""
        assert resolve_local_path(None) is None

    def test_expands_tilde(self, monkeypatch):
        fake_home = os.path.normpath("/home/alice")
        monkeypatch.setenv("HOME", fake_home)
        monkeypatch.setenv("USERPROFILE", fake_home)
        expanded = resolve_local_path("~/tools/rigger.py")
        assert expanded == os.path.normpath(os.path.join(fake_home, "tools", "rigger.py"))

    def test_expands_env_var(self, monkeypatch):
        monkeypatch.setenv("STUDIO", os.path.normpath("/srv/studio"))
        expanded = resolve_local_path("$STUDIO/tools/foo.py")
        assert expanded == os.path.normpath("/srv/studio/tools/foo.py")

    def test_roundtrip_through_home(self, monkeypatch):
        fake_home = os.path.normpath("/home/alice")
        monkeypatch.setenv("HOME", fake_home)
        monkeypatch.setenv("USERPROFILE", fake_home)
        original = os.path.join(fake_home, "tools", "rigger.py")
        stored = store_local_path(original)
        assert resolve_local_path(stored) == os.path.normpath(original)
