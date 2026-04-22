"""Tests for ScriptManager.launch fall-through guards.

A common user failure mode is registering a folder whose package.json
lacks ``entry_point`` — installed.json then records an empty dict, and
launch used to silently no-op because none of the type branches matched.
These tests pin the loud-failure behaviour so the bug can't regress into
silence again.
"""

import pytest

from carton.core.script_manager import ScriptManager


class _DummyEnv:
    """Minimal env_manager stub — launch's guard-path doesn't touch env."""
    pass


@pytest.fixture
def sm():
    return ScriptManager(config=None, install_manager=None,
                         env_manager=_DummyEnv())


class TestLaunchFallThroughGuard:
    def test_empty_entry_point_raises(self, sm):
        pkg_data = {
            "type": "python_package",
            "source": "local",
            "entry_point": {},
        }
        with pytest.raises(RuntimeError, match="no usable 'type'"):
            sm.launch(pkg_data)

    def test_missing_entry_point_key_raises(self, sm):
        pkg_data = {
            "type": "python_package",
            "source": "local",
        }
        with pytest.raises(RuntimeError, match="no usable 'type'"):
            sm.launch(pkg_data)

    def test_unknown_type_raises(self, sm):
        pkg_data = {
            "type": "python_package",
            "source": "local",
            "entry_point": {"type": "martian"},
        }
        with pytest.raises(RuntimeError, match="unknown entry_point type"):
            sm.launch(pkg_data)

    def test_error_describes_available_keys(self, sm):
        """The guard message names which keys were present so the user can
        see what shape was persisted (and what's missing)."""
        pkg_data = {
            "type": "python_package",
            "source": "local",
            "entry_point": {"module": "foo", "function": "show"},
        }
        with pytest.raises(RuntimeError, match="function, module"):
            sm.launch(pkg_data)
