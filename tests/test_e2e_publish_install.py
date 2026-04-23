"""End-to-end: publish a fake tool and install it from a different Config.

Exercises the full publisher → catalogue → downloader → installer path
in-process, catching contract mismatches between Publisher and
InstallManager that the individual unit tests would miss (zip layout,
pkg_id keying, relative download_url resolution, etc.).

The test uses only the local filesystem — no HTTP server — so it runs
in the same ~0.1s budget as the rest of the suite.
"""

import json
import os
import tempfile
import zipfile

from carton.core.catalogue_client import CatalogueClient
from carton.core.config import Config, CatalogueEntry
from carton.core.downloader import Downloader
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager
from carton.core.personal_catalogue import PersonalCatalogue
from carton.core.publisher import Publisher


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
    def test_publish_then_install_from_separate_config(self, tmp_path):
        # Layout:
        #   tmp/source/hello_proj/hello_tool/  -- nested project
        #   tmp/catalogue/catalogue.json       -- shared local catalogue
        #   tmp/publisher_home/                -- publisher-side Config.install_dir
        #   tmp/consumer_home/                 -- consumer-side Config.install_dir
        source_root = os.path.join(str(tmp_path), "source")
        catalogue_root = os.path.join(str(tmp_path), "catalogue")
        publisher_home = os.path.join(str(tmp_path), "publisher_home")
        consumer_home = os.path.join(str(tmp_path), "consumer_home")
        os.makedirs(source_root)
        os.makedirs(catalogue_root)

        src_pkg = _make_nested_source_package(source_root)
        catalogue_path = os.path.join(catalogue_root, "catalogue.json")
        catalogue_entry = CatalogueEntry(catalogue_path, display_name="e2e-local")

        # --- Publisher side ---
        pub_config = Config(
            install_dir=publisher_home,
            catalogues=[catalogue_entry],
        )
        publisher = Publisher(pub_config)

        pkg_data = _make_pkg_data(src_pkg)
        result = publisher.publish(
            pkg_data, catalogue_entry, namespace="e2e",
        )

        pkg_id = result["id"]
        assert pkg_id == "e2e/hello_tool"
        assert result["version"] == "1.0.0"

        # Catalogue state after publish: v5.0 shape.
        assert os.path.isfile(catalogue_path)
        with open(catalogue_path, "r", encoding="utf-8") as f:
            cat_json = json.load(f)
        assert cat_json["schema_version"] == "5.0"
        assert cat_json["catalogue_id"]  # stamped on first publish
        assert pkg_id in cat_json["packages"]
        entry = cat_json["packages"][pkg_id]
        origin = entry["origin"]
        assert origin["type"] == "embedded"
        assert origin["latest_version"] == "1.0.0"
        assert "1.0.0" in origin["versions"]
        ver_info = origin["versions"]["1.0.0"]
        assert ver_info["download_url"].endswith("hello_tool-1.0.0.zip")
        assert len(ver_info["sha256"]) == 64
        assert ver_info["size_bytes"] > 0

        # Published zip exists and has the canonical package.json injected
        zip_abs = os.path.join(
            catalogue_root, "packages", "e2e", "hello_tool", "1.0.0",
            "hello_tool-1.0.0.zip",
        )
        assert os.path.isfile(zip_abs)
        with zipfile.ZipFile(zip_abs, "r") as zf:
            names = zf.namelist()
            # Publisher zips the project root's CONTENTS — the nested
            # ``hello_tool/`` folder shows up as a subdirectory inside
            # the zip (this is what makes ``import hello_tool`` work
            # after install).
            assert "package.json" in names
            assert any(n.endswith("hello_tool/__init__.py")
                       or n.endswith("hello_tool\\__init__.py")
                       for n in names)
            inner_meta = json.loads(zf.read("package.json").decode("utf-8"))
            assert inner_meta["namespace"] == "e2e"
            assert inner_meta["name"] == "hello_tool"
            assert inner_meta["version"] == "1.0.0"
            # v5.0 zip: no schema_version, no home_registry — just the
            # package-scoped manifest the runtime needs.
            assert "schema_version" not in inner_meta
            assert "home_registry" not in inner_meta
            # home_origin is the v5.0 pointer back at the catalogue.
            assert inner_meta["home_origin"]["type"] == "embedded"
            assert inner_meta["home_origin"]["catalogue_name"] == "e2e-local"

        # v0.5 source-sacred: Carton must not back-stamp the author's
        # source tree. The dedicated source-sacred tests live in
        # tests/test_publisher_home_origin_stamping.py; here we only
        # assert the absence of the stamp that earlier versions wrote.
        assert not os.path.exists(os.path.join(src_pkg, "package.json"))

        # --- Consumer side (different Config, same catalogue) ---
        cons_config = Config(
            install_dir=consumer_home,
            catalogues=[catalogue_entry],
        )
        client = CatalogueClient(
            cons_config,
            personal_catalogue=PersonalCatalogue(),
        )
        client.fetch()
        packages = client.get_packages()

        assert pkg_id in packages, \
            "Consumer CatalogueClient did not see the published package"
        pkg_entry = packages[pkg_id]
        latest = pkg_entry["latest_version"]
        version_info = pkg_entry["versions"][latest]
        resolved_url = version_info["download_url"]
        # CatalogueClient should have resolved the relative download_url
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
        }
        install_mgr.install_package(staged_zip, meta)

        # Installed state
        assert install_mgr.is_installed(pkg_id)
        assert install_mgr.get_installed_version(pkg_id) == "1.0.0"

        installed_entry = install_mgr.get_installed_packages()[pkg_id]
        assert installed_entry["namespace"] == "e2e"
        assert installed_entry["name"] == "hello_tool"
        # v4.0: sha256 / entry_point / display_name are no longer
        # duplicated into installed.json. The catalogue version_entry
        # is the SoT for sha256, the inner package.json for entry_point.
        assert "sha256" not in installed_entry
        assert "entry_point" not in installed_entry
        assert "display_name" not in installed_entry

        # entry_point still resolves correctly via the resolver, which
        # reads the zip's inner package.json from the install dir.
        from carton.core.entry_point_resolver import resolve_entry_point
        pkg_dir_abs = os.path.join(
            consumer_home, "packages", "e2e", "hello_tool",
        )
        ep = resolve_entry_point({}, package_dir=pkg_dir_abs)
        assert ep["module"] == "hello_tool"
        assert ep["function"] == "show"

        # Extracted content is present and runnable as Python source.
        # The nested project layout means the importable module sits
        # one level under the package dir.
        extracted_init = os.path.join(
            consumer_home, "packages", "e2e", "hello_tool",
            "hello_tool", "__init__.py",
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


def _make_nested_source_package(root):
    """Create a properly-nested Python project (project_root/hello_tool/).

    ``root`` is the parent; the returned path is the project root that
    ``local_path`` should point at. This layout passes the publisher's
    post-3.0 flat-layout validator.
    """
    project_root = os.path.join(root, "hello_proj")
    module_dir = os.path.join(project_root, "hello_tool")
    os.makedirs(module_dir, exist_ok=True)
    with open(os.path.join(module_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(
            '"""hello_tool — E2E fixture."""\n'
            '__version__ = "1.0.0"\n'
            'def show():\n'
            '    return "hello from e2e"\n'
        )
    return project_root


class TestPublishViaRemoteMirror:
    """Publishing through a remote entry routes the write to its local mirror.

    Simulates the "ぐるぐる (remote S3) → carton-guru2 (local source)" flow
    without actually going over HTTP — the publisher's probe for the
    remote's UUID is monkeypatched so we can avoid the network.
    """

    def test_remote_entry_routes_to_local_mirror(self, monkeypatch, tmp_path):
        source_root = os.path.join(str(tmp_path), "source")
        mirror_root = os.path.join(str(tmp_path), "mirror")
        publisher_home = os.path.join(str(tmp_path), "pub_home")
        os.makedirs(source_root)
        os.makedirs(mirror_root)

        src_pkg = _make_nested_source_package(source_root)
        mirror_path = os.path.join(mirror_root, "catalogue.json")

        # Pre-seed the mirror with a catalogue_id (v5.0 shape) so the
        # publisher can match the remote against it on the first call.
        shared_uuid = "77777777-8888-4999-8aaa-bbbbbbbbbbbb"
        with open(mirror_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": "5.0",
                "catalogue_id": shared_uuid,
                "packages": {},
            }, f)
        os.makedirs(os.path.join(mirror_root, "packages"))

        mirror_entry = CatalogueEntry(
            mirror_path, catalogue_id=shared_uuid,
            display_name="carton-guru2",
        )
        remote_entry = CatalogueEntry(
            "https://example.com/guru2/catalogue.json",
            display_name="ぐるぐる",
        )
        # The remote exposes the same UUID via the probe path.
        from carton.core.publisher import Publisher as PubCls
        monkeypatch.setattr(
            PubCls, "_probe_remote_catalogue_id",
            staticmethod(lambda e: shared_uuid),
        )

        pub_config = Config(
            install_dir=publisher_home,
            catalogues=[mirror_entry, remote_entry],
        )
        publisher = Publisher(pub_config)

        pkg_data = _make_pkg_data(src_pkg)
        result = publisher.publish(
            pkg_data, remote_entry, namespace="e2e",
        )

        # Confirm the publish landed in the LOCAL mirror, not anywhere
        # near the URL.
        with open(mirror_path, "r", encoding="utf-8") as f:
            cat_json = json.load(f)
        assert result["id"] in cat_json["packages"]
        assert cat_json["catalogue_id"] == shared_uuid
        assert cat_json["schema_version"] == "5.0"
        # ``published_via`` signals the user-visible remote entry.
        assert result["published_via"] == "ぐるぐる"

        zip_abs = os.path.join(
            mirror_root, "packages", "e2e", "hello_tool", "1.0.0",
            "hello_tool-1.0.0.zip",
        )
        assert os.path.isfile(zip_abs)

        # v0.5 source-sacred: no back-stamp on the author's source.
        # The catalogue_id convergence that used to be verified here is
        # now enforced on the catalogue/zip side — which is the side the
        # consumer actually reads.
        assert not os.path.exists(os.path.join(src_pkg, "package.json"))
