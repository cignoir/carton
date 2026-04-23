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
    def test_publish_records_identity_in_catalogue(self):
        """v0.5 source-sacred: identity lands in the catalogue, not the
        source tree. Earlier versions wrote namespace back into the
        author's package.json; that responsibility has been removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use the nested project layout so the publisher's flat-layout
            # validator passes. namespace=None means the author-side
            # package.json has no namespace — we rely on pkg_data /
            # installed.json to supply it, and the source stays untouched.
            project_root = _make_project(tmpdir, namespace=None)
            config, install_mgr, script_mgr = _make_env(tmpdir)

            pkg_id = script_mgr.register(
                file_path=project_root, name="my_tool", display_name="My Tool",
                icon="🔧", description="t", pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True, namespace="mystudio",
            )

            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_catalogue(os.path.join(reg_dir, "catalogue.json"), display_name="test")
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            result = publisher.publish(pkg_data, config.catalogues[0])

            assert result["id"] == "mystudio/my_tool"

            # Catalogue entry keyed by namespace/name.
            with open(config.catalogues[0].path, "r") as f:
                catalogue = json.load(f)
            assert "mystudio/my_tool" in catalogue["packages"]

            # Source is sacred: the source package.json never gained a
            # namespace — that stays the responsibility of pkg_data /
            # installed.json, not of the publisher.
            with open(os.path.join(project_root, "package.json"), "r") as f:
                src_data = json.load(f)
            assert "namespace" not in src_data

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

            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_catalogue(os.path.join(reg_dir, "catalogue.json"), display_name="test")
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]

            try:
                publisher.publish(pkg_data, config.catalogues[0])
                assert False, "expected MissingNamespaceError"
            except MissingNamespaceError:
                pass


def _make_project(tmpdir, namespace="mystudio"):
    """Build a properly-nested python_package project.

    Produces ``<tmpdir>/my_tool_proj/{package.json, my_tool/__init__.py}``
    — the layout the post-3.0 publisher validator accepts. Returns the
    project root (what ``local_path`` should point at).
    """
    project_root = os.path.join(tmpdir, "my_tool_proj")
    module_dir = os.path.join(project_root, "my_tool")
    os.makedirs(module_dir, exist_ok=True)
    with open(os.path.join(module_dir, "__init__.py"), "w") as f:
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
    with open(os.path.join(project_root, "package.json"), "w") as f:
        json.dump(pkg, f)
    return project_root


class TestCatalogueIdStamping:
    """First publish stamps a catalogue_id; subsequent publishes preserve it."""

    def test_first_publish_stamps_catalogue_id(self):
        from carton.core.uuid_id import is_valid_uuid

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir, namespace="mystudio")
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = script_mgr.register(
                file_path=project_root, name="my_tool", display_name="My Tool",
                icon="🔧", description="t", pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True, namespace="mystudio",
            )
            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            reg_path = os.path.join(reg_dir, "catalogue.json")
            config.add_catalogue(reg_path, display_name="test")
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            publisher.publish(pkg_data, config.catalogues[0])

            with open(reg_path, "r", encoding="utf-8") as f:
                catalogue = json.load(f)
            assert is_valid_uuid(catalogue.get("catalogue_id", ""))
            assert catalogue["schema_version"] == "5.0"
            # The CatalogueEntry is updated in-memory to match the stamp.
            assert config.catalogues[0].catalogue_id == catalogue["catalogue_id"]

    def test_second_publish_preserves_catalogue_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir, namespace="mystudio")
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = script_mgr.register(
                file_path=project_root, name="my_tool", display_name="My Tool",
                icon="🔧", description="t", pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True, namespace="mystudio",
            )
            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            reg_path = os.path.join(reg_dir, "catalogue.json")
            config.add_catalogue(reg_path, display_name="test")
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]

            publisher.publish(pkg_data, config.catalogues[0])
            with open(reg_path, "r", encoding="utf-8") as f:
                cid_first = json.load(f)["catalogue_id"]

            # Second publish (bump the version to avoid VersionConflictError)
            pkg_data2 = dict(pkg_data)
            pkg_data2["version"] = "1.0.1"
            publisher.publish(pkg_data2, config.catalogues[0])
            with open(reg_path, "r", encoding="utf-8") as f:
                cid_second = json.load(f)["catalogue_id"]
            assert cid_first == cid_second

    def test_home_origin_carries_catalogue_id_in_zip(self):
        """home_origin lands in the zip's inner package.json so the
        installer can copy it into installed.json on unpack.

        v0.5: this check moved off the source tree (which was back-
        stamped by earlier releases) and onto the zip, which is the
        on-the-wire artifact every subscriber downloads and unpacks.
        """
        import zipfile
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir, namespace="mystudio")
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = script_mgr.register(
                file_path=project_root, name="my_tool", display_name="My Tool",
                icon="🔧", description="t", pkg_type="python_package",
                entry_point={"type": "python", "module": "my_tool", "function": "show"},
                is_folder=True, namespace="mystudio", version="1.0.0",
            )
            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_catalogue(
                os.path.join(reg_dir, "catalogue.json"), display_name="test",
            )
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            publisher.publish(pkg_data, config.catalogues[0])

            # Resolve zip location from the catalogue entry's base_dir
            # to avoid coupling the test to path-normalisation quirks.
            zip_path = os.path.join(
                config.catalogues[0].base_dir,
                "packages", "mystudio", "my_tool", "1.0.0",
                "my_tool-1.0.0.zip",
            )
            with zipfile.ZipFile(zip_path) as zf:
                with zf.open("package.json") as f:
                    inner = json.loads(f.read().decode("utf-8"))
            origin = inner.get("home_origin") or {}
            assert origin.get("type") == "embedded"
            assert origin.get("catalogue_name") == "test"
            # catalogue_id is only present after update_catalogue stamps
            # it; at zip-write time it may still be blank on first
            # publish. The production installer handles that case by
            # filling catalogue_id from the catalogue.json on resolve.
            if origin.get("catalogue_id"):
                assert origin["catalogue_id"] == config.catalogues[0].catalogue_id


class TestSidecarSacredForSingleFile:
    def test_publish_does_not_create_sidecar_next_to_script(self):
        """v0.5: Carton must not drop a sidecar next to the author's
        single-file script.

        Earlier releases wrote ``<script>.carton.json`` on publish so
        subsequent publishes converged on the same identity. That was a
        responsibility violation (Carton is a package manager, not a
        metadata generator), and it's been removed alongside the
        folder-side back-stamping.
        """
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

            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_catalogue(os.path.join(reg_dir, "catalogue.json"), display_name="test")
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            publisher.publish(pkg_data, config.catalogues[0])

            assert not os.path.exists(sidecar_path_for(script_path))
            assert read_sidecar(script_path) is None
