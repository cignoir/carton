"""Tests for v5.0 ``home_origin`` stamping in :class:`Publisher` publishes.

Follow-up to the ``home_origin`` alias layer (commit ``e7921ef``): both
:meth:`Publisher.publish` (embedded) and :meth:`Publisher.publish_github`
now stamp a ``home_origin`` payload into

* the zip artifact's inner ``package.json``, and
* the source tree's ``package.json`` / ``.carton.json`` sidecar,

so consumers that have migrated to the v5.0 field see the right variant
without having to guess it from ``home_registry``.

Precedence is ``pkg_data["home_origin"]`` > auto-built variant, mirroring
the existing ``home_registry`` rule so a tool whose home is elsewhere
(e.g. an embedded-but-mirrored-to-github publish) keeps the caller's
shape rather than being overwritten with the target's.
"""

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


# ---- publish_github (github-origin) --------------------------------------

class TestGithubPublishStamping:
    @pytest.fixture
    def publisher(self, tmp_path):
        cfg = Config(install_dir=str(tmp_path / "install"))
        os.makedirs(cfg.staging_dir, exist_ok=True)
        return Publisher(cfg)

    def test_zip_package_json_has_github_home_origin(self, publisher, tmp_path):
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

    def test_source_package_json_has_github_home_origin(self, publisher, tmp_path):
        local = _make_tool_for_github(tmp_path)
        gh = _StubGh(available=True)
        publisher.publish_github(
            _pkg_data_for_github(local),
            repo="mystudio/my_tool",
            gh_cli_module=gh,
        )
        with open(os.path.join(local, "package.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["home_origin"] == {
            "type": "github", "repo": "mystudio/my_tool",
        }

    def test_caller_home_origin_wins_over_repo(self, publisher, tmp_path):
        """A tool whose real home is elsewhere (e.g. embedded in a private
        catalogue) but is being mirrored to github keeps the caller's
        home_origin rather than being overwritten."""
        local = _make_tool_for_github(tmp_path)
        caller_home = {"type": "embedded", "catalogue_name": "internal"}
        gh = _StubGh(available=True)
        publisher.publish_github(
            _pkg_data_for_github(local, home_origin=caller_home),
            repo="mystudio/my_tool-mirror",
            gh_cli_module=gh,
        )
        # Source tree stamped with the caller's shape, not the mirror repo.
        with open(os.path.join(local, "package.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["home_origin"] == caller_home

    def test_legacy_home_registry_still_stamped(self, publisher, tmp_path):
        """home_origin addition must not displace the existing
        home_registry pass-through — the alias period keeps both shapes
        side-by-side until Step 4-B consumer migration."""
        local = _make_tool_for_github(tmp_path)
        legacy = {"name": "studio-main", "registry_id": "a" * 8 + "-" + "a" * 4
                  + "-" + "a" * 4 + "-" + "a" * 4 + "-" + "a" * 12}
        gh = _StubGh(available=True)
        publisher.publish_github(
            _pkg_data_for_github(local, home_registry=legacy),
            repo="mystudio/my_tool",
            gh_cli_module=gh,
        )
        with open(os.path.join(local, "package.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["home_registry"] == legacy
        # home_origin is independently auto-built from the repo since
        # pkg_data didn't carry one; this is the alias-period "no auto-sync"
        # rule in action.
        assert data["home_origin"] == {"type": "github", "repo": "mystudio/my_tool"}


# ---- publish (embedded-origin) -------------------------------------------

class TestEmbeddedPublishStamping:
    def test_zip_package_json_has_embedded_home_origin(self):
        """Embedded publish stamps home_origin={type:embedded,...} into the
        zip's inner package.json.

        Note: catalogue_id may be missing on a first publish — the zip is
        built before ``_update_registry`` generates/reads the registry_id,
        same tightness as the pre-existing ``to_home_meta`` path. The
        source tree persists happens after stamping, so the source-tree
        counterpart test verifies catalogue_id convergence.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir)
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = _register(script_mgr, project_root)

            reg_dir = os.path.join(tmpdir, "registry")
            os.makedirs(reg_dir, exist_ok=True)
            reg_path = os.path.join(reg_dir, "registry.json")
            config.add_catalogue("studio-main", reg_path)
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            publisher.publish(pkg_data, config.catalogues[0])

            # Zip lands at packages/<ns>/<name>/<version>/<name>-<version>.zip
            zip_path = os.path.join(
                reg_dir, "packages", "mystudio", "my_tool",
                "1.0.0", "my_tool-1.0.0.zip",
            )
            inner = _read_zip_package_json(zip_path)
            origin = inner.get("home_origin") or {}
            assert origin.get("type") == "embedded"
            assert origin.get("catalogue_name") == "studio-main"

    def test_source_package_json_has_embedded_home_origin(self):
        """Source tree is persisted AFTER ``_update_registry`` stamps the
        registry_id, so the home_origin written back here carries the
        catalogue_id too — this is the path consumers on this machine
        resolve from."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir)
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = _register(script_mgr, project_root)

            reg_dir = os.path.join(tmpdir, "registry")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_catalogue("studio-main", os.path.join(reg_dir, "registry.json"))
            publisher = Publisher(config)
            pkg_data = install_mgr.get_installed_packages()[pkg_id]
            publisher.publish(pkg_data, config.catalogues[0])

            with open(os.path.join(project_root, "package.json"), "r",
                      encoding="utf-8") as f:
                data = json.load(f)
            origin = data.get("home_origin") or {}
            assert origin.get("type") == "embedded"
            assert origin.get("catalogue_name") == "studio-main"
            # The stamped registry_id propagates to home_origin too.
            assert origin.get("catalogue_id") == config.catalogues[0].catalogue_id

    def test_caller_home_origin_wins_over_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _make_project(tmpdir)
            config, install_mgr, script_mgr = _make_env(tmpdir)
            pkg_id = _register(script_mgr, project_root)

            reg_dir = os.path.join(tmpdir, "registry")
            os.makedirs(reg_dir, exist_ok=True)
            config.add_catalogue("mirror", os.path.join(reg_dir, "registry.json"))
            publisher = Publisher(config)

            pkg_data = dict(install_mgr.get_installed_packages()[pkg_id])
            caller_home = {"type": "github", "repo": "mystudio/my_tool"}
            pkg_data["home_origin"] = caller_home
            publisher.publish(pkg_data, config.catalogues[0])

            with open(os.path.join(project_root, "package.json"), "r",
                      encoding="utf-8") as f:
                data = json.load(f)
            # Caller's shape survives; target "mirror" embedded variant
            # did NOT overwrite it.
            assert data["home_origin"] == caller_home
