"""Tests for MayaEnvManager — tracking, removal, and transactional helpers."""

import os
import sys

import pytest

from carton.core.env_manager import MayaEnvManager


@pytest.fixture
def clean_state():
    """Snapshot sys.path and Maya env vars; restore after each test."""
    saved_path = list(sys.path)
    saved_env = {
        k: os.environ.get(k)
        for k in ("MAYA_SCRIPT_PATH", "MAYA_PLUG_IN_PATH", "XBMLANGPATH")
    }
    yield
    sys.path[:] = saved_path
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class TestBookkeeping:
    def test_remove_env_path_updates_tracking_dict(self, clean_state):
        env = MayaEnvManager()
        env.add_env_path("MAYA_SCRIPT_PATH", "/tmp/scripts_A")
        assert "/tmp/scripts_A" in env._added_paths["MAYA_SCRIPT_PATH"]

        env.remove_env_path("MAYA_SCRIPT_PATH", "/tmp/scripts_A")

        # Both the live env var AND the tracker must have dropped it.
        assert "/tmp/scripts_A" not in os.environ.get("MAYA_SCRIPT_PATH", "")
        assert "MAYA_SCRIPT_PATH" not in env._added_paths

    def test_remove_python_path_updates_tracking_dict(self, clean_state):
        env = MayaEnvManager()
        p = os.path.normpath("/tmp/pypath_A")
        env.add_python_path(p)
        assert p in sys.path
        assert p in env._added_paths["sys.path"]

        env.remove_python_path(p)

        assert p not in sys.path
        assert "sys.path" not in env._added_paths

    def test_remove_missing_entry_is_noop(self, clean_state):
        """Removing a path we never tracked should not raise."""
        env = MayaEnvManager()
        env.remove_python_path("/tmp/never_added")  # no crash
        env.remove_env_path("MAYA_SCRIPT_PATH", "/tmp/never_added")


class TestSnapshotDiff:
    def test_diff_reports_adds_since_snapshot(self, clean_state):
        env = MayaEnvManager()
        pre = os.path.normpath("/tmp/preexisting")
        new_py = os.path.normpath("/tmp/new_py")
        env.add_python_path(pre)

        before = env.snapshot()
        env.add_python_path(new_py)
        env.add_env_path("MAYA_SCRIPT_PATH", "/tmp/new_mel")

        diff = env.diff_since(before)
        assert diff == {
            "sys.path": [new_py],
            "MAYA_SCRIPT_PATH": ["/tmp/new_mel"],
        }
        # Preexisting path is NOT reported.
        assert pre not in diff.get("sys.path", [])

    def test_snapshot_is_deep_copied(self, clean_state):
        env = MayaEnvManager()
        a = os.path.normpath("/tmp/a")
        b = os.path.normpath("/tmp/b")
        env.add_python_path(a)
        before = env.snapshot()
        env.add_python_path(b)
        # before should not have been mutated by the later add
        assert before["sys.path"] == [a]

    def test_empty_diff_when_nothing_added(self, clean_state):
        env = MayaEnvManager()
        env.add_python_path(os.path.normpath("/tmp/a"))
        before = env.snapshot()
        # No new adds
        assert env.diff_since(before) == {}


class TestRemoveTracked:
    def test_removes_all_entries_from_diff(self, clean_state):
        env = MayaEnvManager()
        ia = os.path.normpath("/tmp/install_a")
        before = env.snapshot()
        env.add_python_path(ia)
        env.add_env_path("MAYA_SCRIPT_PATH", "/tmp/install_b")
        env.add_env_path("MAYA_PLUG_IN_PATH", "/tmp/install_c")

        diff = env.diff_since(before)
        env.remove_tracked(diff)

        assert ia not in sys.path
        assert "/tmp/install_b" not in os.environ.get("MAYA_SCRIPT_PATH", "")
        assert "/tmp/install_c" not in os.environ.get("MAYA_PLUG_IN_PATH", "")
        assert env._added_paths == {}

    def test_idempotent_when_paths_already_gone(self, clean_state):
        env = MayaEnvManager()
        before = env.snapshot()
        env.add_python_path("/tmp/gone_already")
        diff = env.diff_since(before)

        # Simulate the handler having already removed it
        env.remove_python_path("/tmp/gone_already")

        # remove_tracked should not blow up — it's legal to call twice
        env.remove_tracked(diff)
        assert "/tmp/gone_already" not in sys.path

    def test_empty_or_none_is_noop(self, clean_state):
        env = MayaEnvManager()
        env.remove_tracked(None)
        env.remove_tracked({})


class TestCleanupAll:
    def test_removes_every_tracked_entry(self, clean_state):
        env = MayaEnvManager()
        env.add_python_path("/tmp/one")
        env.add_env_path("MAYA_SCRIPT_PATH", "/tmp/two")
        env.cleanup_all()
        assert "/tmp/one" not in sys.path
        assert "/tmp/two" not in os.environ.get("MAYA_SCRIPT_PATH", "")
        assert env._added_paths == {}
