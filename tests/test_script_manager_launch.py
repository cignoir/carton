"""Tests for ScriptManager.launch fall-through guards.

A common user failure mode is registering a folder whose package.json
lacks ``entry_point`` — installed.json then records an empty dict, and
launch used to silently no-op because none of the type branches matched.
These tests pin the loud-failure behaviour so the bug can't regress into
silence again.
"""

import os
import sys
import tempfile
import types

import pytest

from carton.core.config import Config
from carton.core.env_manager import MayaEnvManager
from carton.core.script_manager import ScriptManager, _delete_dockable_wrapper


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
            "entry_point": {"random": "junk", "another": "key"},
        }
        with pytest.raises(RuntimeError, match="another, random"):
            sm.launch(pkg_data)

    def test_typeless_module_dict_is_promoted_and_launches(self, sm):
        """launch() normalizes legacy shapes itself now — a typeless
        ``{"module": ...}`` dict no longer dead-ends at the guard, it is
        promoted to a python entry and dispatched (import failure here
        proves it got past the guard to importlib)."""
        pkg_data = {
            "type": "python_package",
            "source": "local",
            "entry_point": {"module": "mmc_no_such_module_xyz",
                            "function": "show"},
        }
        with pytest.raises(ModuleNotFoundError):
            sm.launch(pkg_data)


# ---------- Dev reload --------------------------------------------------


@pytest.fixture
def clean_env():
    """Snapshot sys.path and sys.modules so tests can leak modules freely."""
    saved_path = list(sys.path)
    saved_modules = set(sys.modules.keys())
    yield
    sys.path[:] = saved_path
    for m in list(sys.modules.keys()):
        if m not in saved_modules:
            del sys.modules[m]


def _make_pkg(parent_dir, name="mmc_devreload_pkg"):
    """Write a minimal python_package whose ``show()`` is a no-op.

    The package itself is intentionally inert — tests stamp a sentinel
    attribute onto its module after the first launch and assert whether the
    second launch wiped that attribute (= fresh import) or kept it (= cached).
    """
    pkg_dir = os.path.join(parent_dir, name)
    os.makedirs(pkg_dir)
    with open(os.path.join(pkg_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("def show():\n    return None\n")
    return name, pkg_dir


def _pkg_data(local_path, module_name, source="local"):
    return {
        "type": "python_package",
        "source": source,
        "local_path": local_path,
        "is_folder": True,
        "entry_point": {
            "type": "python",
            "module": module_name,
            "function": "show",
        },
    }


class TestDevReloadOnLaunch:
    def test_my_tools_with_flag_on_evicts_cache(self, clean_env, tmp_path):
        cfg = Config(dev_reload_my_tools=True)
        sm = ScriptManager(config=cfg, install_manager=None,
                           env_manager=MayaEnvManager())
        name, pkg_dir = _make_pkg(str(tmp_path))
        data = _pkg_data(pkg_dir, name)

        sm.launch(data)
        assert name in sys.modules
        sys.modules[name]._sentinel = "from-first-launch"

        sm.launch(data)
        # Module came back from a fresh import — sentinel wiped.
        assert name in sys.modules
        assert not hasattr(sys.modules[name], "_sentinel")

    def test_my_tools_with_flag_off_keeps_cache(self, clean_env, tmp_path):
        cfg = Config(dev_reload_my_tools=False)
        sm = ScriptManager(config=cfg, install_manager=None,
                           env_manager=MayaEnvManager())
        name, pkg_dir = _make_pkg(str(tmp_path), name="mmc_dr_off_pkg")
        data = _pkg_data(pkg_dir, name)

        sm.launch(data)
        sys.modules[name]._sentinel = "keep-me"
        sm.launch(data)
        assert getattr(sys.modules[name], "_sentinel", None) == "keep-me"

    def test_registry_install_skips_reload(self, clean_env, tmp_path):
        """A pure registry install (no local_path) is not My Tools, so even
        with the flag on the cached module survives — ordinary users keep
        the fast cached-import path on every launch."""
        cfg = Config(dev_reload_my_tools=True)
        sm = ScriptManager(config=cfg, install_manager=None,
                           env_manager=MayaEnvManager())
        name, pkg_dir = _make_pkg(str(tmp_path), name="mmc_registry_pkg")
        # Mimic an installed-from-catalogue entry: source=registry and no
        # local_path. local_path is set to the temp dir only so the test
        # path can be wired up without an InstallManager.
        data = _pkg_data(pkg_dir, name, source="registry")
        data.pop("local_path")
        # Drop the path on manually since the launch path bails on absent
        # local_path — register the parent dir so the import resolves.
        sys.path.insert(0, str(tmp_path))

        sm.launch(data)
        sys.modules[name]._sentinel = "registry-keep"
        sm.launch(data)
        assert getattr(sys.modules[name], "_sentinel", None) == "registry-keep"

    def test_first_launch_with_no_cache_works(self, clean_env, tmp_path):
        """No cached entry yet → reload branch is a no-op and fresh import
        runs through the normal path."""
        cfg = Config(dev_reload_my_tools=True)
        sm = ScriptManager(config=cfg, install_manager=None,
                           env_manager=MayaEnvManager())
        name, pkg_dir = _make_pkg(str(tmp_path), name="mmc_first_launch_pkg")
        data = _pkg_data(pkg_dir, name)

        assert name not in sys.modules
        sm.launch(data)
        assert name in sys.modules

    def test_config_none_disables_reload(self, clean_env, tmp_path):
        """ScriptManager(config=None) is a legitimate test construction —
        it must not crash on the dev-reload check, and the cached-import
        behaviour matches flag-off."""
        sm = ScriptManager(config=None, install_manager=None,
                           env_manager=MayaEnvManager())
        name, pkg_dir = _make_pkg(str(tmp_path), name="mmc_no_config_pkg")
        data = _pkg_data(pkg_dir, name)

        sm.launch(data)
        sys.modules[name]._sentinel = "config-none"
        sm.launch(data)
        assert getattr(sys.modules[name], "_sentinel", None) == "config-none"


# ---------- Dockable wrapper cleanup --------------------------------------


class _FakeWidget:
    """Just enough surface for ``_delete_dockable_wrapper``."""
    def __init__(self, name):
        self._name = name
    def objectName(self):
        return self._name
    def setParent(self, parent):
        pass
    def hide(self):
        pass


def _stub_maya_cmds(monkeypatch, existing_controls):
    """Install a fake ``maya.cmds`` whose workspaceControl/deleteUI record calls."""
    calls = []
    cmds_stub = types.ModuleType("maya.cmds")

    def workspaceControl(name, **kw):
        calls.append(("workspaceControl", name, kw))
        if kw.get("exists"):
            return name in existing_controls
        return None

    def deleteUI(name):
        calls.append(("deleteUI", name))
        existing_controls.discard(name)

    cmds_stub.workspaceControl = workspaceControl
    cmds_stub.deleteUI = deleteUI
    maya_mod = types.ModuleType("maya")
    maya_mod.cmds = cmds_stub
    monkeypatch.setitem(sys.modules, "maya", maya_mod)
    monkeypatch.setitem(sys.modules, "maya.cmds", cmds_stub)
    return calls


class TestDeleteDockableWrapper:
    def test_deletes_existing_control(self, monkeypatch):
        existing = {"MyWidgetWorkspaceControl"}
        calls = _stub_maya_cmds(monkeypatch, existing)

        _delete_dockable_wrapper(_FakeWidget("MyWidget"))

        assert ("deleteUI", "MyWidgetWorkspaceControl") in calls
        assert "MyWidgetWorkspaceControl" not in existing

    def test_noop_when_control_absent(self, monkeypatch):
        """Tools that never opted into dockable mode have no workspaceControl
        — the cleanup helper must not call deleteUI in that case."""
        calls = _stub_maya_cmds(monkeypatch, set())

        _delete_dockable_wrapper(_FakeWidget("FreestandingWidget"))

        assert not any(call[0] == "deleteUI" for call in calls)

    def test_noop_when_widget_has_no_object_name(self, monkeypatch):
        """Without an objectName Maya can't have built a named control for
        us, so we shouldn't ask deleteUI to chase a phantom name."""
        calls = _stub_maya_cmds(monkeypatch, {"WorkspaceControl"})

        _delete_dockable_wrapper(_FakeWidget(""))

        assert not any(call[0] == "deleteUI" for call in calls)

    def test_silent_when_maya_unavailable(self, monkeypatch):
        """Outside Maya the helper must not raise — dev-reload tests run
        without maya.cmds installed."""
        # Make sure no ``maya.cmds`` is masquerading from a previous test.
        for k in [k for k in list(sys.modules) if k == "maya" or k.startswith("maya.")]:
            monkeypatch.delitem(sys.modules, k, raising=False)
        # Block the import explicitly so it definitely fails.
        monkeypatch.setitem(sys.modules, "maya", None)

        # Should return without raising.
        _delete_dockable_wrapper(_FakeWidget("AnyName"))
