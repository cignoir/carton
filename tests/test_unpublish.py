"""Tests for unpublish functionality."""

import json
import os
import tempfile

from carton.core.config import Config, CatalogueEntry
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager
from carton.core.publisher import Publisher
from carton.core.script_manager import ScriptManager


def _make_tool_folder(tmpdir, version="1.0.0"):
    """Create a properly-nested project folder for publishing.

    Layout: ``<tmpdir>/my_tool_proj/{package.json, my_tool/__init__.py}`` —
    the layout the publisher's flat-layout validator accepts.
    """
    project_root = os.path.join(tmpdir, "my_tool_proj")
    module_dir = os.path.join(project_root, "my_tool")
    os.makedirs(module_dir, exist_ok=True)
    with open(os.path.join(module_dir, "__init__.py"), "w") as f:
        f.write("def show(): pass\n")
    pkg = {
        "namespace": "mystudio",
        "name": "my_tool",
        "display_name": "My Tool",
        "version": version,
        "type": "python_package",
        "entry_point": {"type": "python", "module": "my_tool", "function": "show"},
    }
    with open(os.path.join(project_root, "package.json"), "w") as f:
        json.dump(pkg, f)
    return project_root


def _setup_env(tmpdir):
    """Create config, install manager, script manager, publisher, and registry."""
    config = Config(install_dir=tmpdir)
    env = MayaEnvManager()
    install_mgr = InstallManager(config, env)
    script_mgr = ScriptManager(config, install_mgr, env)

    reg_dir = os.path.join(tmpdir, "registry")
    os.makedirs(reg_dir, exist_ok=True)
    config.add_catalogue("test", os.path.join(reg_dir, "catalogue.json"))
    registry_entry = config.catalogues[0]

    publisher = Publisher(config)
    return config, install_mgr, script_mgr, publisher, registry_entry


def _register_and_publish(tmpdir, version="1.0.0"):
    """Helper: register a tool and publish it. Returns all objects."""
    tool_dir = _make_tool_folder(tmpdir, version=version)
    config, install_mgr, script_mgr, publisher, reg_entry = _setup_env(tmpdir)

    pkg_id = script_mgr.register(
        file_path=tool_dir,
        name="my_tool",
        display_name="My Tool",
        icon="🔧",
        description="test tool",
        pkg_type="python_package",
        entry_point={"type": "python", "module": "my_tool", "function": "show"},
        is_folder=True,
        version=version,
        namespace="mystudio",
    )

    pkg_data = install_mgr.get_installed_packages()[pkg_id]
    publisher.publish(pkg_data, reg_entry)

    return pkg_id, tool_dir, config, install_mgr, script_mgr, publisher, reg_entry


class TestUnpublish:
    """Publisher.unpublish() should remove package from registry."""

    def test_unpublish_removes_catalogue_entry(self):
        """After unpublish, the package should not exist in catalogue.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_id, _, _, _, _, publisher, reg_entry = _register_and_publish(tmpdir)

            publisher.unpublish(pkg_id, reg_entry)

            with open(reg_entry.path, "r", encoding="utf-8") as f:
                catalogue = json.load(f)
            assert pkg_id not in catalogue["packages"]

    def test_unpublish_deletes_zip_files(self):
        """After unpublish, the package directory should be removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_id, _, _, _, _, publisher, reg_entry = _register_and_publish(tmpdir)

            pkg_dir = os.path.join(reg_entry.base_dir, "packages", "mystudio", "my_tool")
            assert os.path.isdir(pkg_dir)

            publisher.unpublish(pkg_id, reg_entry)

            assert not os.path.exists(pkg_dir)

    def test_unpublish_returns_package_info(self):
        """unpublish() should return dict with id and name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_id, _, _, _, _, publisher, reg_entry = _register_and_publish(tmpdir)

            result = publisher.unpublish(pkg_id, reg_entry)

            assert result["id"] == pkg_id
            assert result["name"] == "my_tool"

    def test_unpublish_nonexistent_raises(self):
        """Unpublishing a package not in catalogue should raise RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, config, _, _, publisher, reg_entry = _register_and_publish(tmpdir)

            try:
                publisher.unpublish("mystudio/nonexistent", reg_entry)
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "not found" in str(e)

    def test_unpublish_preserves_other_packages(self):
        """Unpublishing one package should not affect others in the same catalogue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Publish first package
            pkg_id_1, _, config, install_mgr, script_mgr, publisher, reg_entry = (
                _register_and_publish(tmpdir)
            )

            # Publish a second package (nested layout for the validator)
            tool_dir_2 = os.path.join(tmpdir, "other_proj")
            module_dir_2 = os.path.join(tool_dir_2, "other_tool")
            os.makedirs(module_dir_2, exist_ok=True)
            with open(os.path.join(module_dir_2, "__init__.py"), "w") as f:
                f.write("def show(): pass\n")
            with open(os.path.join(tool_dir_2, "package.json"), "w") as f:
                json.dump({
                    "namespace": "mystudio",
                    "name": "other_tool",
                    "display_name": "Other Tool",
                    "version": "1.0.0",
                    "type": "python_package",
                    "entry_point": {"type": "python", "module": "other_tool", "function": "show"},
                }, f)

            pkg_id_2 = script_mgr.register(
                file_path=tool_dir_2,
                name="other_tool",
                display_name="Other Tool",
                icon="📦",
                description="another tool",
                pkg_type="python_package",
                entry_point={"type": "python", "module": "other_tool", "function": "show"},
                is_folder=True,
                version="1.0.0",
                namespace="mystudio",
            )
            pkg_data_2 = install_mgr.get_installed_packages()[pkg_id_2]
            publisher.publish(pkg_data_2, reg_entry)

            # Unpublish the first
            publisher.unpublish(pkg_id_1, reg_entry)

            # Second should still be there
            with open(reg_entry.path, "r", encoding="utf-8") as f:
                catalogue = json.load(f)
            assert pkg_id_1 not in catalogue["packages"]
            assert pkg_id_2 in catalogue["packages"]


class TestFindPublishedRegistries:
    """Publisher.find_published_catalogues() should find where a package is published."""

    def test_finds_catalogue_with_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_id, _, _, _, _, publisher, reg_entry = _register_and_publish(tmpdir)

            results = publisher.find_published_catalogues(pkg_id)

            assert len(results) == 1
            assert results[0].name == reg_entry.name

    def test_returns_empty_when_not_published(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, _, _, _, publisher, _ = _register_and_publish(tmpdir)

            results = publisher.find_published_catalogues("mystudio/nonexistent")

            assert results == []

    def test_returns_empty_after_unpublish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_id, _, _, _, _, publisher, reg_entry = _register_and_publish(tmpdir)

            publisher.unpublish(pkg_id, reg_entry)
            results = publisher.find_published_catalogues(pkg_id)

            assert results == []
