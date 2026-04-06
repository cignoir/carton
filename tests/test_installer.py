"""Tests for InstallManager."""

import os
import sys
import tempfile
import zipfile

import pytest

from carton.core.config import Config
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager, InstallError

_PKG_ID = "mystudio/test_pkg"


@pytest.fixture
def clean_sys_path():
    """Save and restore sys.path around a test."""
    saved = list(sys.path)
    yield
    sys.path[:] = saved


def _make_test_zip(tmpdir, pkg_name="test_pkg"):
    """Create a test zip file."""
    zip_path = os.path.join(tmpdir, "{}-1.0.0.zip".format(pkg_name))
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "{}/__init__.py".format(pkg_name),
            '__version__ = "1.0.0"\ndef show(): pass\n',
        )
    return zip_path


class TestInstallManager:
    def test_install_and_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            env = MayaEnvManager()
            mgr = InstallManager(config, env)

            zip_path = _make_test_zip(tmpdir)
            meta = {
                "id": _PKG_ID,
                "namespace": "mystudio",
                "name": "test_pkg",
                "version": "1.0.0",
                "type": "python_package",
                "display_name": "Test Package",
                "entry_point": {"type": "python", "module": "test_pkg", "function": "show"},
            }
            mgr.install_package(zip_path, meta)

            assert mgr.is_installed(_PKG_ID)
            assert mgr.get_installed_version(_PKG_ID) == "1.0.0"
            entry = mgr.get_installed_packages()[_PKG_ID]
            assert entry["namespace"] == "mystudio"
            assert entry["path"] == "packages/mystudio/test_pkg"

    def test_uninstall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            env = MayaEnvManager()
            mgr = InstallManager(config, env)

            zip_path = _make_test_zip(tmpdir)
            meta = {
                "id": _PKG_ID,
                "namespace": "mystudio",
                "name": "test_pkg",
                "version": "1.0.0",
                "type": "python_package",
                "entry_point": {"type": "python", "module": "test_pkg", "function": "show"},
            }
            mgr.install_package(zip_path, meta)
            mgr.uninstall_package(_PKG_ID)

            assert not mgr.is_installed(_PKG_ID)

    def test_rollback_on_corrupt_zip_fresh_install(self):
        """A bad zip on a fresh install must raise and leave nothing behind."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            mgr = InstallManager(config, MayaEnvManager())

            bad_zip = os.path.join(tmpdir, "bad.zip")
            with open(bad_zip, "wb") as f:
                f.write(b"this is not a zip file")

            meta = {
                "id": _PKG_ID,
                "namespace": "mystudio",
                "name": "test_pkg",
                "version": "1.0.0",
                "type": "python_package",
                "entry_point": {"type": "python", "module": "test_pkg", "function": "show"},
            }

            with pytest.raises(InstallError):
                mgr.install_package(bad_zip, meta)

            assert not mgr.is_installed(_PKG_ID)
            assert not os.path.isdir(
                os.path.join(tmpdir, "packages", "mystudio", "test_pkg")
            )

    def test_rollback_restores_previous_version(self):
        """A failed upgrade must restore the previously installed version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            mgr = InstallManager(config, MayaEnvManager())

            # Install v1.0.0 successfully
            good_zip = _make_test_zip(tmpdir)
            meta_v1 = {
                "id": _PKG_ID,
                "namespace": "mystudio",
                "name": "test_pkg",
                "version": "1.0.0",
                "type": "python_package",
                "entry_point": {"type": "python", "module": "test_pkg", "function": "show"},
            }
            mgr.install_package(good_zip, meta_v1)
            pkg_dir = os.path.join(tmpdir, "packages", "mystudio", "test_pkg")
            assert os.path.isfile(os.path.join(pkg_dir, "test_pkg", "__init__.py"))

            # Attempt to upgrade to v2.0.0 with a corrupt zip
            bad_zip = os.path.join(tmpdir, "bad-2.0.0.zip")
            with open(bad_zip, "wb") as f:
                f.write(b"garbage")
            meta_v2 = dict(meta_v1)
            meta_v2["version"] = "2.0.0"

            with pytest.raises(InstallError):
                mgr.install_package(bad_zip, meta_v2)

            # v1.0.0 must still be installed and its files intact
            assert mgr.get_installed_version(_PKG_ID) == "1.0.0"
            assert os.path.isfile(os.path.join(pkg_dir, "test_pkg", "__init__.py"))
            # No leftover backup directories
            leftovers = [d for d in os.listdir(os.path.join(tmpdir, "packages", "mystudio"))
                         if "carton-bak" in d]
            assert leftovers == []

    def test_install_records_activated_paths(self, clean_sys_path):
        """Install must capture the handler's env diff into activated_paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            mgr = InstallManager(config, MayaEnvManager())

            zip_path = _make_test_zip(tmpdir)
            meta = {
                "id": _PKG_ID,
                "namespace": "mystudio",
                "name": "test_pkg",
                "version": "1.0.0",
                "type": "python_package",
                "entry_point": {"type": "python", "module": "test_pkg", "function": "show"},
            }
            mgr.install_package(zip_path, meta)

            entry = mgr.get_installed_packages()[_PKG_ID]
            assert "activated_paths" in entry
            # PythonPackageHandler adds package_dir to sys.path. Normalize
            # because InstallManager builds rel_path with forward slashes
            # (good for cross-platform registry.json) which mix with the
            # tmpdir's native separator on Windows.
            pkg_dir = entry["activated_paths"]["sys.path"][0]
            assert pkg_dir in sys.path
            assert pkg_dir.endswith(os.path.join("mystudio", "test_pkg").replace(os.sep, "/")) \
                or pkg_dir.endswith(os.path.join("mystudio", "test_pkg"))

    def test_uninstall_replays_activated_paths(self, clean_sys_path):
        """Even if a handler forgets to clean env, uninstall should catch it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            env = MayaEnvManager()
            mgr = InstallManager(config, env)

            zip_path = _make_test_zip(tmpdir)
            meta = {
                "id": _PKG_ID,
                "namespace": "mystudio",
                "name": "test_pkg",
                "version": "1.0.0",
                "type": "python_package",
                "entry_point": {"type": "python", "module": "test_pkg", "function": "show"},
            }
            mgr.install_package(zip_path, meta)
            # Read back the exact path the installer used so our separator
            # matches whatever Windows-flavored form it produced.
            pkg_dir = mgr.get_installed_packages()[_PKG_ID]["activated_paths"]["sys.path"][0]
            assert pkg_dir in sys.path

            # Re-inject the path after install as if some other code path
            # (or a buggy handler) had added it back. uninstall should
            # still remove it via the recorded diff.
            sys.path.insert(0, pkg_dir)
            env._added_paths.setdefault("sys.path", []).append(pkg_dir)

            mgr.uninstall_package(_PKG_ID)

            # All entries gone, tracker is clean.
            assert sys.path.count(pkg_dir) == 0
            assert "sys.path" not in env._added_paths

    def test_rollback_on_handler_failure(self, monkeypatch):
        """If the handler raises, state must revert to the previous version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            mgr = InstallManager(config, MayaEnvManager())

            good_zip = _make_test_zip(tmpdir)
            meta = {
                "id": _PKG_ID,
                "namespace": "mystudio",
                "name": "test_pkg",
                "version": "1.0.0",
                "type": "python_package",
                "entry_point": {"type": "python", "module": "test_pkg", "function": "show"},
            }
            mgr.install_package(good_zip, meta)

            # Patch get_handler to return a handler that blows up on install
            class _ExplodingHandler:
                def install(self, *a, **kw):
                    raise RuntimeError("boom")

            import carton.core.installer as inst_mod
            monkeypatch.setattr(inst_mod, "get_handler", lambda t: _ExplodingHandler())

            meta_v2 = dict(meta)
            meta_v2["version"] = "2.0.0"
            with pytest.raises(InstallError, match="boom"):
                mgr.install_package(good_zip, meta_v2)

            # Previous version restored
            assert mgr.get_installed_version(_PKG_ID) == "1.0.0"
            pkg_dir = os.path.join(tmpdir, "packages", "mystudio", "test_pkg")
            assert os.path.isfile(os.path.join(pkg_dir, "test_pkg", "__init__.py"))
