"""Tests for MayaModuleHandler path resolution and idempotency."""

import os
import sys
import tempfile

from carton.core.handlers.maya_module_handler import (
    MayaModuleHandler,
    resolve_paths,
    _ACTIVATED_DIRS,
)
from carton.core.env_manager import MayaEnvManager


def _make_application_package(tmp):
    """Build an Autodesk-style folder: PackageContents.xml + Contents/{scripts,plug-ins/win64/2024}."""
    folder = os.path.join(tmp, "TestMod")
    os.makedirs(os.path.join(folder, "Contents", "scripts", "testmod"))
    os.makedirs(os.path.join(folder, "Contents", "plug-ins", "win64", "2024"))
    os.makedirs(os.path.join(folder, "Contents", "icons"))
    with open(os.path.join(folder, "PackageContents.xml"), "w") as f:
        f.write('<ApplicationPackage Name="TestMod"/>\n')
    with open(os.path.join(folder, "Contents", "scripts", "userSetup.py"), "w") as f:
        f.write("MARKER = 1\n")
    with open(os.path.join(folder, "Contents", "scripts", "testmod", "__init__.py"), "w") as f:
        f.write("def show(): pass\n")
    # Drop a fake plugin file so the plug-ins/win64/2024 dir is detected
    with open(os.path.join(folder, "Contents", "plug-ins", "win64", "2024", "fake.mll"), "wb") as f:
        f.write(b"")
    return folder


def _make_bare_module(tmp):
    """Build a .mod-style folder: MyMod.mod + scripts/ + plug-ins/."""
    folder = os.path.join(tmp, "MyMod")
    os.makedirs(os.path.join(folder, "scripts"))
    os.makedirs(os.path.join(folder, "plug-ins"))
    with open(os.path.join(folder, "MyMod.mod"), "w") as f:
        f.write("+ MyMod 1.0 .\nscripts: scripts\nplug-ins: plug-ins\n")
    with open(os.path.join(folder, "plug-ins", "fake.py"), "w") as f:
        f.write("# stub")
    return folder


class TestResolvePaths:
    def test_application_package_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _make_application_package(tmp)
            paths = resolve_paths(folder)
            assert paths["scripts"].endswith(os.path.join("Contents", "scripts"))
            assert paths["icons"].endswith(os.path.join("Contents", "icons"))
            # plug-in dir walked one level deep to find win64/2024
            assert any("2024" in d for d in paths["plug_in_dirs"])
            assert paths["user_setup"].endswith("userSetup.py")

    def test_bare_mod_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _make_bare_module(tmp)
            paths = resolve_paths(folder)
            assert paths["scripts"].endswith("scripts")
            assert paths["plug_in_dirs"][0].endswith("plug-ins")


class TestActivation:
    def setup_method(self, _method):
        _ACTIVATED_DIRS.clear()

    def test_install_adds_paths_to_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _make_application_package(tmp)
            env = MayaEnvManager()
            handler = MayaModuleHandler()

            handler.install(folder, {}, env)

            scripts_dir = os.path.join(folder, "Contents", "scripts")
            assert scripts_dir in sys.path

    def test_activate_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _make_application_package(tmp)
            env = MayaEnvManager()
            handler = MayaModuleHandler()

            handler.activate(folder, {}, env)
            handler.activate(folder, {}, env)

            scripts_dir = os.path.join(folder, "Contents", "scripts")
            # sys.path should contain the dir but not duplicated infinitely
            assert sys.path.count(scripts_dir) <= 1
            assert os.path.normpath(folder) in _ACTIVATED_DIRS

    def test_uninstall_removes_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _make_application_package(tmp)
            env = MayaEnvManager()
            handler = MayaModuleHandler()

            handler.install(folder, {}, env)
            scripts_dir = os.path.join(folder, "Contents", "scripts")
            assert scripts_dir in sys.path

            handler.uninstall(folder, {}, env)
            assert scripts_dir not in sys.path
            assert not os.path.exists(folder)
            assert os.path.normpath(folder) not in _ACTIVATED_DIRS
