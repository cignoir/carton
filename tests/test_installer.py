"""Tests for InstallManager."""

import json
import os
import tempfile
import zipfile

from carton.core.config import Config
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager

_TEST_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


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
                "id": _TEST_UUID,
                "name": "test_pkg",
                "version": "1.0.0",
                "type": "python_package",
                "display_name": "Test Package",
                "entry_point": {"type": "python", "module": "test_pkg", "function": "show"},
            }
            mgr.install_package(zip_path, meta)

            assert mgr.is_installed(_TEST_UUID)
            assert mgr.get_installed_version(_TEST_UUID) == "1.0.0"

    def test_uninstall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            env = MayaEnvManager()
            mgr = InstallManager(config, env)

            zip_path = _make_test_zip(tmpdir)
            meta = {
                "id": _TEST_UUID,
                "name": "test_pkg",
                "version": "1.0.0",
                "type": "python_package",
                "entry_point": {"type": "python", "module": "test_pkg", "function": "show"},
            }
            mgr.install_package(zip_path, meta)
            mgr.uninstall_package(_TEST_UUID)

            assert not mgr.is_installed(_TEST_UUID)

    def test_migrate_v1_to_v2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Config(install_dir=tmpdir)
            installed_data = {
                "schema_version": "1.0",
                "packages": {
                    "old-pkg-uuid": {
                        "version": "1.0.0",
                        "entry_point": "old_pkg:show",
                        "path": "packages/old-pkg",
                    }
                },
            }
            path = config.installed_json_path
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(installed_data, f)

            env = MayaEnvManager()
            mgr = InstallManager(config, env)

            pkgs = mgr.get_installed_packages()
            assert pkgs["old-pkg-uuid"]["type"] == "python_package"
            assert pkgs["old-pkg-uuid"]["source"] == "registry"
