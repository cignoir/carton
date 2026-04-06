"""Tests for namespace/name identity persistence (formerly UUID persistence).

These tests cover the convergence property: when source code is shared via
version control, two users adding & publishing the same tool should land on
the same registry entry.
"""

import json
import os
import tempfile

from carton.core.config import Config
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager
from carton.core.publisher import Publisher, MissingNamespaceError
from carton.core.script_manager import ScriptManager
from carton.core.sidecar import sidecar_path_for, read_sidecar


def _make_folder(tmpdir, namespace=None):
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
    if namespace:
        pkg["namespace"] = namespace
    with open(os.path.join(tool_dir, "package.json"), "w") as f:
        json.dump(pkg, f)
    return tool_dir


def _make_env(tmpdir):
    config = Config(install_dir=tmpdir)
    env = MayaEnvManager()
    install_mgr = InstallManager(config, env)
    script_mgr = ScriptManager(config, install_mgr, env)
    return config, install_mgr, script_mgr


class TestNamespaceRegistration:
    def test_register_uses_namespace_name_as_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_dir = _make_folder(tmpdir, namespace="mystudio")
            _, _, script_mgr = _make_env(tmpdir)

            pkg_id = script_mgr.register(
                file_path=tool_dir, name="my_tool", display_name="My Tool",
                icon="🔧", description="t", pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True, namespace="mystudio",
            )
            assert pkg_id == "mystudio/my_tool"

    def test_register_without_namespace_uses_bare_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_dir = _make_folder(tmpdir)
            _, _, script_mgr = _make_env(tmpdir)

            pkg_id = script_mgr.register(
                file_path=tool_dir, name="my_tool", display_name="My Tool",
                icon="🔧", description="t", pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True,
            )
            assert pkg_id == "my_tool"


class TestPublishPersistence:
    def test_publish_writes_namespace_to_package_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_dir = _make_folder(tmpdir)
            config, install_mgr, script_mgr = _make_env(tmpdir)

            pkg_id = script_mgr.register(
                file_path=tool_dir, name="my_tool", display_name="My Tool",
                icon="🔧", description="t", pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True, namespace="mystudio",
            )

            reg_dir = os.path.join(tmpdir, "registry")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_registry("test", os.path.join(reg_dir, "registry.json"))
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            result = publisher.publish(pkg_data, config.registries[0])

            assert result["id"] == "mystudio/my_tool"

            with open(os.path.join(tool_dir, "package.json"), "r") as f:
                data = json.load(f)
            assert data["namespace"] == "mystudio"
            assert "id" not in data

            # Registry entry keyed by namespace/name
            with open(config.registries[0].path, "r") as f:
                registry = json.load(f)
            assert "mystudio/my_tool" in registry["packages"]

    def test_publish_without_namespace_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tool_dir = _make_folder(tmpdir)
            config, install_mgr, script_mgr = _make_env(tmpdir)

            pkg_id = script_mgr.register(
                file_path=tool_dir, name="my_tool", display_name="My Tool",
                icon="🔧", description="t", pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True,
            )

            reg_dir = os.path.join(tmpdir, "registry")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_registry("test", os.path.join(reg_dir, "registry.json"))
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]

            try:
                publisher.publish(pkg_data, config.registries[0])
                assert False, "expected MissingNamespaceError"
            except MissingNamespaceError:
                pass


class TestSidecarPersistenceForSingleFile:
    def test_publish_creates_sidecar_for_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, "rename.py")
            with open(script_path, "w") as f:
                f.write("def show(): pass\n")
            config, install_mgr, script_mgr = _make_env(tmpdir)

            pkg_id = script_mgr.register(
                file_path=script_path, name="rename", display_name="Rename",
                icon="🔧", description="t", pkg_type="python_package",
                entry_point={"type": "python", "module": "rename", "function": "show"},
                is_folder=False, namespace="mystudio",
            )

            reg_dir = os.path.join(tmpdir, "registry")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_registry("test", os.path.join(reg_dir, "registry.json"))
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            publisher.publish(pkg_data, config.registries[0])

            # Sidecar should now exist next to the script
            assert os.path.exists(sidecar_path_for(script_path))
            sc = read_sidecar(script_path)
            assert sc["namespace"] == "mystudio"
            assert sc["name"] == "rename"
