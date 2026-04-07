"""End-to-end: publish a fake tool and install it from a different Config.

This exercises the full publisher -> registry -> downloader -> installer
path in-process, catching contract mismatches between Publisher and
InstallManager that the individual unit tests would miss (zip layout,
pkg_id keying, relative download_url resolution, etc.).

The test uses only the local filesystem — no HTTP server — so it runs
in the same ~0.1s budget as the rest of the suite.
"""

import json
import os
import tempfile
import zipfile

import pytest

from carton.core.config import Config, RegistryEntry
from carton.core.downloader import Downloader
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager
from carton.core.publisher import Publisher
from carton.core.registry_client import RegistryClient


def _make_source_package(root):
    """Create a fake folder-style Python package under ``root``."""
    pkg_root = os.path.join(root, "hello_tool")
    os.makedirs(pkg_root)
    with open(os.path.join(pkg_root, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(
            '"""hello_tool — E2E fixture."""\n'
            '__version__ = "1.0.0"\n'
            'def show():\n'
            '    return "hello from e2e"\n'
        )
    return pkg_root


def _make_pkg_data(local_path, version="1.0.0"):
    """Build the publisher-side pkg_data dict for a folder package."""
    return {
        "name": "hello_tool",
        "display_name": "Hello Tool",
        "version": version,
        "type": "python_package",
        "description": "E2E smoke test package",
        "author": "e2e",
        "icon": "",
        "entry_point": {
            "type": "python",
            "module": "hello_tool",
            "function": "show",
        },
        "is_folder": True,
        "local_path": local_path,
        "tags": ["e2e"],
    }


class TestPublishInstallRoundtrip:
    def test_publish_then_install_from_separate_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Layout:
            #   tmp/source/hello_tool/      -- raw source folder
            #   tmp/registry/registry.json  -- shared local registry
            #   tmp/publisher_home/         -- publisher-side Config.install_dir
            #   tmp/consumer_home/          -- consumer-side Config.install_dir
            source_root = os.path.join(tmp, "source")
            registry_root = os.path.join(tmp, "registry")
            publisher_home = os.path.join(tmp, "publisher_home")
            consumer_home = os.path.join(tmp, "consumer_home")
            os.makedirs(source_root)
            os.makedirs(registry_root)

            src_pkg = _make_source_package(source_root)
            registry_path = os.path.join(registry_root, "registry.json")
            registry_entry = RegistryEntry("e2e-local", registry_path)

            # --- Publisher side ---
            pub_config = Config(
                install_dir=publisher_home,
                registries=[registry_entry],
            )
            publisher = Publisher(pub_config)

            pkg_data = _make_pkg_data(src_pkg)
            result = publisher.publish(
                pkg_data, registry_entry, namespace="e2e",
            )

            pkg_id = result["id"]
            assert pkg_id == "e2e/hello_tool"
            assert result["version"] == "1.0.0"

            # Registry state after publish
            assert os.path.isfile(registry_path)
            with open(registry_path, "r", encoding="utf-8") as f:
                reg_json = json.load(f)
            assert pkg_id in reg_json["packages"]
            entry = reg_json["packages"][pkg_id]
            assert entry["latest_version"] == "1.0.0"
            assert "1.0.0" in entry["versions"]
            ver_info = entry["versions"]["1.0.0"]
            assert ver_info["download_url"].endswith("hello_tool-1.0.0.zip")
            assert len(ver_info["sha256"]) == 64
            assert ver_info["size_bytes"] > 0

            # Published zip exists and has the canonical package.json injected
            zip_abs = os.path.join(
                registry_root, "packages", "e2e", "hello_tool", "1.0.0",
                "hello_tool-1.0.0.zip",
            )
            assert os.path.isfile(zip_abs)
            with zipfile.ZipFile(zip_abs, "r") as zf:
                names = zf.namelist()
                # Publisher zips the folder's CONTENTS (so the target
                # extract dir itself becomes the Python package).
                assert "package.json" in names
                assert "__init__.py" in names
                inner_meta = json.loads(zf.read("package.json").decode("utf-8"))
                assert inner_meta["namespace"] == "e2e"
                assert inner_meta["name"] == "hello_tool"
                assert inner_meta["version"] == "1.0.0"

            # Source side gained a package.json pinning the identity
            persisted = os.path.join(src_pkg, "package.json")
            assert os.path.isfile(persisted)
            with open(persisted, "r", encoding="utf-8") as f:
                persisted_meta = json.load(f)
            assert persisted_meta["namespace"] == "e2e"
            assert persisted_meta["name"] == "hello_tool"

            # --- Consumer side (different Config, same registry) ---
            cons_config = Config(
                install_dir=consumer_home,
                registries=[registry_entry],
            )
            client = RegistryClient(cons_config)
            client.fetch()
            packages = client.get_packages()

            assert pkg_id in packages, \
                "Consumer RegistryClient did not see the published package"
            pkg_entry = packages[pkg_id]
            latest = pkg_entry["latest_version"]
            version_info = pkg_entry["versions"][latest]
            resolved_url = version_info["download_url"]
            # RegistryClient should have resolved the relative download_url
            # to an absolute local path pointing at the zip on disk.
            assert os.path.isabs(resolved_url) or os.path.isfile(resolved_url)

            downloader = Downloader(cons_config)
            staged_zip = os.path.join(
                cons_config.staging_dir, "hello_tool-1.0.0.zip"
            )
            downloader.download(
                resolved_url, staged_zip,
                expected_sha256=version_info.get("sha256"),
                expected_size=version_info.get("size_bytes"),
            )
            assert os.path.isfile(staged_zip)

            env = MayaEnvManager()
            install_mgr = InstallManager(cons_config, env)

            meta = {
                "id": pkg_id,
                "namespace": pkg_entry.get("namespace", ""),
                "name": pkg_entry["name"],
                "version": latest,
                "type": pkg_entry.get("type", "python_package"),
                "display_name": pkg_entry.get("display_name", pkg_entry["name"]),
                "entry_point": {},
                "sha256": version_info.get("sha256", ""),
            }
            install_mgr.install_package(staged_zip, meta)

            # Installed state
            assert install_mgr.is_installed(pkg_id)
            assert install_mgr.get_installed_version(pkg_id) == "1.0.0"

            installed_entry = install_mgr.get_installed_packages()[pkg_id]
            assert installed_entry["namespace"] == "e2e"
            assert installed_entry["name"] == "hello_tool"
            # SHA256 from the registry should be persisted into installed.json
            assert installed_entry.get("sha256") == version_info["sha256"]
            assert len(installed_entry["sha256"]) == 64
            # entry_point should have been sourced from the inner package.json
            # (we deliberately passed an empty dict in meta to prove it).
            assert installed_entry["entry_point"]["module"] == "hello_tool"
            assert installed_entry["entry_point"]["function"] == "show"

            # Extracted content is present and runnable as Python source
            extracted_init = os.path.join(
                consumer_home, "packages", "e2e", "hello_tool", "__init__.py",
            )
            assert os.path.isfile(extracted_init)
            with open(extracted_init, "r", encoding="utf-8") as f:
                body = f.read()
            assert 'def show' in body
            assert 'hello from e2e' in body

            # installed.json reflects it on disk
            with open(cons_config.installed_json_path, "r", encoding="utf-8") as f:
                installed_json = json.load(f)
            assert pkg_id in installed_json["packages"]

            # --- Uninstall ---
            install_mgr.uninstall_package(pkg_id)
            assert not install_mgr.is_installed(pkg_id)
            pkg_dir = os.path.join(
                consumer_home, "packages", "e2e", "hello_tool",
            )
            assert not os.path.isdir(pkg_dir), \
                "Package directory should be removed after uninstall"
