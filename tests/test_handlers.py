"""Unit tests for package handlers.

These tests pin down the install / uninstall / activate contracts of each
handler in isolation from InstallManager, so that refactoring a handler
can't silently drift the contract out from under the caller.

Maya API side-effects are avoided by:
  * injecting fake ``maya`` / ``maya.cmds`` / ``maya.mel`` modules into
    sys.modules before the handler imports them lazily inside functions.
  * using the real (non-Maya) ``MayaEnvManager`` which only touches
    sys.path and os.environ — both are saved/restored per test.
"""

import os
import sys
import tempfile
import types

import pytest

from carton.core.env_manager import MayaEnvManager
from carton.core.handlers.mel_handler import MelScriptHandler
from carton.core.handlers.plugin_handler import PluginHandler
from carton.core.handlers.python_handler import PythonPackageHandler


@pytest.fixture
def clean_env():
    """Snapshot sys.path, sys.modules keys, and the Maya env vars; restore after."""
    saved_path = list(sys.path)
    saved_modules = set(sys.modules.keys())
    saved_env = {
        k: os.environ.get(k)
        for k in ("MAYA_SCRIPT_PATH", "MAYA_PLUG_IN_PATH",
                  "XBMLANGPATH", "MAYA_PRESET_PATH")
    }
    yield
    sys.path[:] = saved_path
    # Drop any modules the test imported under new names
    for m in list(sys.modules.keys()):
        if m not in saved_modules:
            del sys.modules[m]
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def fake_maya(monkeypatch):
    """Install stub maya / maya.cmds / maya.mel modules so handlers can
    import them without triggering ImportError inside their methods.

    Returns a dict with ``cmds``, ``mel`` stub modules so tests can
    configure call returns and inspect call history.
    """
    maya_mod = types.ModuleType("maya")
    cmds_mod = types.ModuleType("maya.cmds")
    mel_mod = types.ModuleType("maya.mel")

    # Default: pluginInfo(loaded) -> False, so unloadPlugin is a no-op and
    # the uninstall path doesn't error.
    cmds_mod.pluginInfo = lambda *a, **kw: False
    cmds_mod.loadPlugin = lambda *a, **kw: None
    cmds_mod.unloadPlugin = lambda *a, **kw: None

    # mel.eval records calls so tests can assert on them.
    calls = []
    def _eval(expr):
        calls.append(expr)
        return 0
    mel_mod.eval = _eval
    mel_mod._calls = calls

    maya_mod.cmds = cmds_mod
    maya_mod.mel = mel_mod
    monkeypatch.setitem(sys.modules, "maya", maya_mod)
    monkeypatch.setitem(sys.modules, "maya.cmds", cmds_mod)
    monkeypatch.setitem(sys.modules, "maya.mel", mel_mod)
    return {"cmds": cmds_mod, "mel": mel_mod}


# ---------- PythonPackageHandler -------------------------------------------


class TestPythonPackageHandler:
    def test_install_adds_package_dir_to_sys_path(self, clean_env):
        with tempfile.TemporaryDirectory() as pkg_dir:
            env = MayaEnvManager()
            handler = PythonPackageHandler()
            handler.install(pkg_dir, {}, env)
            assert pkg_dir in sys.path

    def test_activate_is_idempotent(self, clean_env):
        with tempfile.TemporaryDirectory() as pkg_dir:
            env = MayaEnvManager()
            handler = PythonPackageHandler()
            handler.activate(pkg_dir, {}, env)
            handler.activate(pkg_dir, {}, env)
            assert sys.path.count(pkg_dir) == 1

    def test_uninstall_removes_path_modules_and_files(self, clean_env):
        with tempfile.TemporaryDirectory() as parent:
            pkg_dir = os.path.join(parent, "hello_pkg")
            os.makedirs(pkg_dir)
            open(os.path.join(pkg_dir, "__init__.py"), "w").close()

            env = MayaEnvManager()
            handler = PythonPackageHandler()
            handler.install(pkg_dir, {}, env)

            # Seed sys.modules with a fake entry for the module we're
            # "uninstalling" so we can assert it gets cleared.
            sys.modules["hello_pkg"] = types.ModuleType("hello_pkg")
            sys.modules["hello_pkg.sub"] = types.ModuleType("hello_pkg.sub")

            meta = {"entry_point": {"module": "hello_pkg", "function": "show"}}
            handler.uninstall(pkg_dir, meta, env)

            assert pkg_dir not in sys.path
            assert "hello_pkg" not in sys.modules
            assert "hello_pkg.sub" not in sys.modules
            assert not os.path.exists(pkg_dir)

    def test_is_loaded_reads_sys_modules(self, clean_env):
        handler = PythonPackageHandler()
        meta = {"entry_point": {"module": "some_random_mod_xyz"}}
        assert handler.is_loaded(meta) is False
        sys.modules["some_random_mod_xyz"] = types.ModuleType("some_random_mod_xyz")
        assert handler.is_loaded(meta) is True
        del sys.modules["some_random_mod_xyz"]


# ---------- MelScriptHandler -----------------------------------------------


class TestMelScriptHandler:
    def test_install_uses_scripts_subdir_when_present(self, clean_env):
        with tempfile.TemporaryDirectory() as pkg_dir:
            scripts = os.path.join(pkg_dir, "scripts")
            os.makedirs(scripts)
            env = MayaEnvManager()
            MelScriptHandler().install(pkg_dir, {}, env)
            assert scripts in os.environ.get("MAYA_SCRIPT_PATH", "").split(os.pathsep)

    def test_install_falls_back_to_package_dir(self, clean_env):
        with tempfile.TemporaryDirectory() as pkg_dir:
            env = MayaEnvManager()
            MelScriptHandler().install(pkg_dir, {}, env)
            assert pkg_dir in os.environ.get("MAYA_SCRIPT_PATH", "").split(os.pathsep)

    def test_uninstall_removes_path_rehashes_and_deletes(self, clean_env, fake_maya):
        with tempfile.TemporaryDirectory() as parent:
            pkg_dir = os.path.join(parent, "mel_pkg")
            scripts = os.path.join(pkg_dir, "scripts")
            os.makedirs(scripts)
            env = MayaEnvManager()
            handler = MelScriptHandler()
            handler.install(pkg_dir, {}, env)
            handler.uninstall(pkg_dir, {}, env)
            assert scripts not in os.environ.get("MAYA_SCRIPT_PATH", "").split(os.pathsep)
            assert "rehash" in fake_maya["mel"]._calls
            assert not os.path.exists(pkg_dir)


# ---------- PluginHandler --------------------------------------------------


class TestPluginHandler:
    def _make_plugin_tree(self, parent):
        pkg = os.path.join(parent, "my_plugin")
        plugins = os.path.join(pkg, "plug-ins")
        scripts = os.path.join(pkg, "scripts")
        os.makedirs(plugins)
        os.makedirs(scripts)
        return pkg, plugins, scripts

    def test_install_adds_plugin_and_scripts_paths(self, clean_env):
        with tempfile.TemporaryDirectory() as parent:
            pkg, plugins, scripts = self._make_plugin_tree(parent)
            env = MayaEnvManager()
            PluginHandler().install(pkg, {}, env)

            assert plugins in os.environ.get("MAYA_PLUG_IN_PATH", "").split(os.pathsep)
            assert scripts in os.environ.get("MAYA_SCRIPT_PATH", "").split(os.pathsep)

    def test_install_without_scripts_dir(self, clean_env):
        with tempfile.TemporaryDirectory() as parent:
            pkg = os.path.join(parent, "bare_plugin")
            os.makedirs(os.path.join(pkg, "plug-ins"))
            env = MayaEnvManager()
            PluginHandler().install(pkg, {}, env)
            # Shouldn't have inserted pkg into MAYA_SCRIPT_PATH when there's
            # no scripts/ to add.
            assert pkg not in os.environ.get("MAYA_SCRIPT_PATH", "").split(os.pathsep)

    def test_uninstall_unloads_plugin_and_cleans_up(self, clean_env, fake_maya):
        with tempfile.TemporaryDirectory() as parent:
            pkg, plugins, scripts = self._make_plugin_tree(parent)
            env = MayaEnvManager()
            handler = PluginHandler()
            handler.install(pkg, {}, env)

            # Make pluginInfo(loaded=True) so the uninstall path exercises
            # the unload branch.
            unloaded = []
            fake_maya["cmds"].pluginInfo = lambda name, **kw: True
            fake_maya["cmds"].unloadPlugin = lambda name: unloaded.append(name)

            meta = {"entry_point": {"plugin_file": "myPlugin.mll"}}
            handler.uninstall(pkg, meta, env)

            assert unloaded == ["myPlugin.mll"]
            assert plugins not in os.environ.get("MAYA_PLUG_IN_PATH", "").split(os.pathsep)
            assert scripts not in os.environ.get("MAYA_SCRIPT_PATH", "").split(os.pathsep)
            assert not os.path.exists(pkg)

    def test_activate_auto_loads_when_configured(self, clean_env, fake_maya):
        with tempfile.TemporaryDirectory() as parent:
            pkg, _, _ = self._make_plugin_tree(parent)
            env = MayaEnvManager()

            loaded = []
            fake_maya["cmds"].pluginInfo = lambda name, **kw: False
            fake_maya["cmds"].loadPlugin = lambda name: loaded.append(name)

            meta = {"entry_point": {
                "plugin_file": "myPlugin.mll",
                "auto_load": True,
            }}
            PluginHandler().activate(pkg, meta, env)
            assert loaded == ["myPlugin.mll"]

    def test_activate_without_auto_load_does_not_load(self, clean_env, fake_maya):
        with tempfile.TemporaryDirectory() as parent:
            pkg, _, _ = self._make_plugin_tree(parent)
            env = MayaEnvManager()

            loaded = []
            fake_maya["cmds"].loadPlugin = lambda name: loaded.append(name)

            meta = {"entry_point": {"plugin_file": "myPlugin.mll"}}
            PluginHandler().activate(pkg, meta, env)
            assert loaded == []
