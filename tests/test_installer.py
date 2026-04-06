"""Tests for InstallManager."""

import os
import tempfile
import zipfile

from carton.core.config import Config
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager

_PKG_ID = "mystudio/test_pkg"


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
