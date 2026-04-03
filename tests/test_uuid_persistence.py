"""Tests for UUID persistence across Remove -> re-Add cycles."""

import json
import os
import tempfile

from carton.core.config import Config
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager
from carton.core.publisher import Publisher
from carton.core.script_manager import ScriptManager

_EXISTING_UUID = "11111111-2222-3333-4444-555555555555"


class TestUuidPersistence:
    """UUID should survive Remove -> re-Add when stored in package.json."""

    def _make_folder_with_package_json(self, tmpdir, pkg_id=None):
        """Create a tool folder with optional UUID in package.json."""
        tool_dir = os.path.join(tmpdir, "my_tool")
        os.makedirs(tool_dir, exist_ok=True)
        with open(os.path.join(tool_dir, "__init__.py"), "w") as f:
            f.write("def show(): pass\n")
        pkg = {
            "name": "my_tool",
            "display_name": "My Tool",
            "version": "1.0.0",
            "type": "python_package",
            "entry_point": {"type": "python", "module": "my_tool", "function": "show"},
        }
        if pkg_id:
            pkg["id"] = pkg_id
        with open(os.path.join(tool_dir, "package.json"), "w") as f:
            json.dump(pkg, f)
        return tool_dir

    def _make_env(self, tmpdir):
        config = Config(install_dir=tmpdir)
        env = MayaEnvManager()
        install_mgr = InstallManager(config, env)
        script_mgr = ScriptManager(config, install_mgr, env)
        return config, install_mgr, script_mgr

    def test_register_reuses_uuid_from_package_json(self):
        """When package.json has an id, register() should reuse it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_dir = self._make_folder_with_package_json(tmpdir, pkg_id=_EXISTING_UUID)
            _, _, script_mgr = self._make_env(tmpdir)

            pkg_id = script_mgr.register(
                file_path=tool_dir,
                name="my_tool",
                display_name="My Tool",
                icon="🔧",
                description="test",
                pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True,
                version="1.0.0",
                pkg_id=_EXISTING_UUID,
            )
            assert pkg_id == _EXISTING_UUID

    def test_register_generates_new_uuid_when_none(self):
        """When no UUID is provided, register() should generate a new one."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_dir = self._make_folder_with_package_json(tmpdir)
            _, _, script_mgr = self._make_env(tmpdir)

            pkg_id = script_mgr.register(
                file_path=tool_dir,
                name="my_tool",
                display_name="My Tool",
                icon="🔧",
                description="test",
                pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True,
                version="1.0.0",
            )
            assert pkg_id is not None
            assert pkg_id != _EXISTING_UUID

    def test_publish_writes_uuid_to_source_package_json(self):
        """Publish should write the UUID back into the source package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_dir = self._make_folder_with_package_json(tmpdir)
            config, install_mgr, script_mgr = self._make_env(tmpdir)

            pkg_id = script_mgr.register(
                file_path=tool_dir,
                name="my_tool",
                display_name="My Tool",
                icon="🔧",
                description="test",
                pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True,
                version="1.0.0",
            )

            # Set up a registry
            reg_dir = os.path.join(tmpdir, "registry")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_registry("test", os.path.join(reg_dir, "registry.json"))
            registry_entry = config.registries[0]

            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            publisher.publish(pkg_data, pkg_id, registry_entry)

            # Verify UUID was written back to source package.json
            with open(os.path.join(tool_dir, "package.json"), "r") as f:
                data = json.load(f)
            assert data["id"] == pkg_id

    def test_full_remove_readd_cycle_keeps_uuid(self):
        """Full cycle: Register -> Publish -> Remove -> re-Add should keep UUID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_dir = self._make_folder_with_package_json(tmpdir)
            config, install_mgr, script_mgr = self._make_env(tmpdir)

            # 1. Register
            pkg_id_1 = script_mgr.register(
                file_path=tool_dir,
                name="my_tool",
                display_name="My Tool",
                icon="🔧",
                description="test",
                pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True,
                version="1.0.0",
            )

            # 2. Publish (writes UUID to package.json)
            reg_dir = os.path.join(tmpdir, "registry")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_registry("test", os.path.join(reg_dir, "registry.json"))
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id_1]
            publisher.publish(pkg_data, pkg_id_1, config.registries[0])

            # 3. Remove
            script_mgr.unregister(pkg_id_1)
            assert pkg_id_1 not in install_mgr.get_installed_packages()

            # 4. Read UUID from package.json (simulating AddDialog reading it)
            with open(os.path.join(tool_dir, "package.json"), "r") as f:
                data = json.load(f)
            persisted_uuid = data.get("id")

            # 5. Re-Add with the persisted UUID
            pkg_id_2 = script_mgr.register(
                file_path=tool_dir,
                name="my_tool",
                display_name="My Tool",
                icon="🔧",
                description="test",
                pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True,
                version="1.1.0",
                pkg_id=persisted_uuid,
            )

            assert pkg_id_2 == pkg_id_1
