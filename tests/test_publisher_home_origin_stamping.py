"""Tests for v5.0 ``home_origin`` handling in :class:`Publisher` publishes.

The v0.5 source-sacred refactor moved ``home_origin`` out of the source
tree entirely. It now lives in two places:

* the zip artifact's inner ``package.json`` (the on-the-wire record), and
* the catalogue.json ``packages[id]`` entry (the authoritative index).

The publisher used to *also* back-stamp the source's ``package.json`` /
``.carton.json`` sidecar. That was a responsibility violation — Carton
is a package manager, not a code generator — and it has been removed.
These tests pin both halves of that contract: what *does* get written
(zip + catalogue), and what *must not* be written (the author's source).
"""

import hashlib
import json
import os
import tempfile
import zipfile

import pytest

from carton.core.config import Config
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager
from carton.core.publisher import Publisher
from carton.core.script_manager import ScriptManager


# ---- shared fixtures (minimal folder layout the publisher accepts) --------

def _make_project(tmpdir, namespace="mystudio"):
    """Same nested layout as test_uuid_persistence._make_project."""
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
        "entry_point": {"type": "python", "module": "my_tool",
                        "function": "show"},
    }
    if namespace:
        pkg["namespace"] = namespace
    with open(os.path.join(project_root, "package.json"), "w") as f:
        json.dump(pkg, f)
    return project_root


def _make_env(tmpdir):
    config = Config(install_dir=tmpdir)
    env = MayaEnvManager()
    install_mgr = InstallManager(config, env)
    script_mgr = ScriptManager(config, install_mgr, env)
    return config, install_mgr, script_mgr


def _register(script_mgr, project_root):
    return script_mgr.register(
        file_path=project_root, name="my_tool", display_name="My Tool",
        icon="🔧", description="t", pkg_type="python_package",
        entry_point={"type": "python", "module": "my_tool", "function": "show"},
        is_folder=True, namespace="mystudio", version="1.0.0",
    )


# ---- gh stub (copied from test_publisher_modes to keep that file intact) --

class _StubGh(object):
    class GhCliError(RuntimeError):
        def __init__(self, message, stderr=""):
            super().__init__(message)
            self.stderr = stderr

    def __init__(self, available=True, release_url="https://x"):
        self._available = available
        self._release_url = release_url
        self.calls = []

    def is_available(self):
        return self._available

    def create_release(self, repo, tag, title="", notes="",
                       assets=None, draft=False, prerelease=False, cwd=None):
        self.calls.append({"repo": repo, "tag": tag, "assets": list(assets or [])})
        return self._release_url

    def build_manual_instructions(self, repo, tag, assets, notes=""):
        return "MANUAL"


def _make_tool_for_github(tmp_path, version="1.0.0"):
    """Minimal python_package layout for publish_github tests."""
    proj = tmp_path / "my_tool_proj"
    module = proj / "my_tool"
    module.mkdir(parents=True)
    (module / "__init__.py").write_text("def show(): pass\n", encoding="utf-8")
    (proj / "package.json").write_text(json.dumps({
        "namespace": "mystudio",
        "name": "my_tool",
        "version": version,
        "type": "python_package",
    }), encoding="utf-8")
    return str(proj)


def _pkg_data_for_github(local_path, version="1.0.0", **extra):
    data = {
        "namespace": "mystudio",
        "name": "my_tool",
        "display_name": "My Tool",
        "version": version,
        "type": "python_package",
        "local_path": local_path,
        "is_folder": True,
        "entry_point": {"type": "python", "module": "my_tool", "function": "show"},
        "author": "tester",
        "description": "t",
        "tags": [],
        "maya_versions": ["2024", "2025"],
    }
    data.update(extra)
    return data


def _read_zip_package_json(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("package.json") as f:
            return json.loads(f.read().decode("utf-8"))


def _snapshot_dir(root):
    """Capture (relative_path, sha256) for every file under ``root``.

    Used to assert a publish operation leaves the source tree byte-for-
    byte identical. Directories are implicit in the file list.
    """
    snapshot = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            abs_path = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_path, root)
            with open(abs_path, "rb") as f:
                snapshot[rel] = hashlib.sha256(f.read()).hexdigest()
    return snapshot


# ---- publish_github (github-origin) --------------------------------------

class TestGithubPublishZipStamping:
    """The zip artifact's inner package.json carries home_origin."""

    @pytest.fixture
    def publisher(self, tmp_path):
        cfg = Config(install_dir=str(tmp_path / "install"))
        os.makedirs(cfg.staging_dir, exist_ok=True)
        return Publisher(cfg)

    def test_zip_has_github_home_origin(self, publisher, tmp_path):
        local = _make_tool_for_github(tmp_path)
        gh = _StubGh(available=True)
        result = publisher.publish_github(
            _pkg_data_for_github(local),
            repo="mystudio/my_tool",
            gh_cli_module=gh,
        )
        inner = _read_zip_package_json(result["zip_path"])
        assert inner["home_origin"] == {
            "type": "github", "repo": "mystudio/my_tool",
        }

    def test_caller_home_origin_wins_in_zip(self, publisher, tmp_path):
        """A tool whose real home is a private catalogue but is being
        mirrored to github keeps the caller's home_origin inside the zip."""
        local = _make_tool_for_github(tmp_path)
        caller_home = {"type": "embedded", "catalogue_name": "internal"}
        gh = _StubGh(available=True)
        result = publisher.publish_github(
            _pkg_data_for_github(local, home_origin=caller_home),
            repo="mystudio/my_tool-mirror",
            gh_cli_module=gh,
        )
        inner = _read_zip_package_json(result["zip_path"])
        assert inner["home_origin"] == caller_home


class TestGithubPublishSourceSacred:
    """publish_github must not mutate the author's source tree."""

    @pytest.fixture
    def publisher(self, tmp_path):
        cfg = Config(install_dir=str(tmp_path / "install"))
        os.makedirs(cfg.staging_dir, exist_ok=True)
        return Publisher(cfg)

    def test_source_tree_is_unchanged_after_publish(self, publisher, tmp_path):
        local = _make_tool_for_github(tmp_path)
        before = _snapshot_dir(local)
        gh = _StubGh(available=True)
        publisher.publish_github(
            _pkg_data_for_github(local),
            repo="mystudio/my_tool",
            gh_cli_module=gh,
        )
        after = _snapshot_dir(local)
        assert after == before, "publish_github wrote to the source tree"

    def test_source_package_json_has_no_home_origin(self, publisher, tmp_path):
        """The author never wrote a home_origin — Carton must not either."""
        local = _make_tool_for_github(tmp_path)
        gh = _StubGh(available=True)
        publisher.publish_github(
            _pkg_data_for_github(local),
            repo="mystudio/my_tool",
            gh_cli_module=gh,
        )
        with open(os.path.join(local, "package.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "home_origin" not in data


# ---- publish (embedded-origin) -------------------------------------------

class TestEmbeddedPublishZipStamping:
    def test_zip_has_embedded_home_origin(self):
        """Embedded publish stamps home_origin={type:embedded,...} into the
        zip's inner package.json.

        catalogue_id may be absent on a first publish — the zip is built
        before update_catalogue generates/reads the id, so this test only
        pins type + catalogue_name.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir)
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = _register(script_mgr, project_root)

            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            reg_path = os.path.join(reg_dir, "catalogue.json")
            config.add_catalogue(reg_path, display_name="studio-main")
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            publisher.publish(pkg_data, config.catalogues[0])

            zip_path = os.path.join(
                reg_dir, "packages", "mystudio", "my_tool",
                "1.0.0", "my_tool-1.0.0.zip",
            )
            inner = _read_zip_package_json(zip_path)
            origin = inner.get("home_origin") or {}
            assert origin.get("type") == "embedded"
            assert origin.get("catalogue_name") == "studio-main"

    def test_caller_home_origin_wins_in_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir)
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = _register(script_mgr, project_root)

            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            reg_path = os.path.join(reg_dir, "catalogue.json")
            config.add_catalogue(reg_path, display_name="mirror")
            publisher = Publisher(config)

            pkg_data = dict(install_mgr.get_installed_packages()[pkg_id])
            caller_home = {"type": "github", "repo": "mystudio/my_tool"}
            pkg_data["home_origin"] = caller_home
            publisher.publish(pkg_data, config.catalogues[0])

            zip_path = os.path.join(
                reg_dir, "packages", "mystudio", "my_tool",
                "1.0.0", "my_tool-1.0.0.zip",
            )
            inner = _read_zip_package_json(zip_path)
            assert inner["home_origin"] == caller_home


class TestEmbeddedPublishSourceSacred:
    """publish (embedded) must not mutate the author's source tree."""

    def test_source_tree_is_unchanged_after_publish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir)
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = _register(script_mgr, project_root)

            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_catalogue(
                os.path.join(reg_dir, "catalogue.json"),
                display_name="studio-main",
            )
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]

            before = _snapshot_dir(project_root)
            publisher.publish(pkg_data, config.catalogues[0])
            after = _snapshot_dir(project_root)

            assert after == before, "publish wrote to the source tree"

    def test_source_package_json_has_no_home_origin_after_publish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir)
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = _register(script_mgr, project_root)

            reg_dir = os.path.join(tmpdir, "catalogue")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_catalogue(
                os.path.join(reg_dir, "catalogue.json"),
                display_name="studio-main",
            )
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            publisher.publish(pkg_data, config.catalogues[0])

            with open(os.path.join(project_root, "package.json"), "r",
                      encoding="utf-8") as f:
                data = json.load(f)
            # The author never wrote a home_origin; Carton must not add one.
            assert "home_origin" not in data
