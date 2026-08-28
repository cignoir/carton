"""Tests for the installer builder script.

Verifies the placeholder substitution path (template -> generated .py)
and the first-install seed semantics encoded into the template.
"""

import importlib.util
import json
import os
import sys

import pytest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_PATH = os.path.join(REPO_ROOT, "carton", "data", "install_carton.template.py")
BUILDER_PATH = os.path.join(REPO_ROOT, "scripts", "build_installer.py")


def _load_builder():
    """Import build_installer.py as a module under a unique name."""
    spec = importlib.util.spec_from_file_location("_carton_build_installer", BUILDER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBuilderPlaceholderSubstitution:
    def test_default_build_writes_null_seed(self, tmp_path, monkeypatch):
        builder = _load_builder()
        monkeypatch.setattr(builder, "DIST_DIR", str(tmp_path))
        out_path = tmp_path / "install_carton_test.py"
        builder.build(version="9.9.9", profile_path=None, output=str(out_path))

        content = out_path.read_text(encoding="utf-8")
        assert "SEED_CONFIG = None" in content
        assert 'CARTON_VERSION = "9.9.9"' in content

    def test_profile_build_inlines_seed_dict(self, tmp_path, monkeypatch):
        # Use an HTTPS path so CatalogueEntry doesn't run os.path.normpath
        # on it (which would mangle slashes on Windows and break the
        # substring assertions below).
        profile_path = tmp_path / "studio.json"
        profile_path.write_text(json.dumps({
            "catalogues": [{
                "display_name": "s", "path": "https://example.com/r.json",
            }],
            "language": "ja",
            "auto_check_updates": False,
            "github_repo": "acme/carton",
            "proxy": "http://p:8080",
        }), encoding="utf-8")

        builder = _load_builder()
        monkeypatch.setattr(builder, "DIST_DIR", str(tmp_path))
        out_path = tmp_path / "install_studio.py"
        builder.build(
            version="1.2.3",
            profile_path=str(profile_path),
            output=str(out_path),
        )

        content = out_path.read_text(encoding="utf-8")
        # The SEED_CONFIG line is a Python dict literal (so the generated
        # installer can be import'd directly without a runtime parse).
        assert "SEED_CONFIG = {" in content
        for needle in ("'language': 'ja'", "'auto_check_updates': False",
                       "'proxy': 'http://p:8080'", "'acme/carton'",
                       "'https://example.com/r.json'"):
            assert needle in content, "missing {}".format(needle)
        # Language picked from profile, not hardcoded
        assert 'CARTON_LANGUAGE = "ja"' in content


class TestTemplateSeedSemantics:
    """Exercise the seeding decision tree without actually running Maya.

    We can't import the generated installer (it has top-level Maya
    imports inside functions, but the dispatch is conditional, so module
    import alone is safe). We use exec to load it into a fresh namespace,
    then call the config-write block via a tiny shim.
    """

    def _load_generated(self, tmp_path, monkeypatch, seed):
        """Build an installer with the given seed and return its module."""
        if seed is not None:
            profile_path = tmp_path / "p.json"
            profile_path.write_text(json.dumps(seed), encoding="utf-8")
            profile_arg = str(profile_path)
        else:
            profile_arg = None

        builder = _load_builder()
        monkeypatch.setattr(builder, "DIST_DIR", str(tmp_path))
        out_path = tmp_path / "installer.py"
        builder.build(
            version="0.0.1",
            profile_path=profile_arg,
            output=str(out_path),
        )

        # Load the generated installer as a module. Maya imports inside
        # onMayaDroppedPythonFile() are deferred, so module-level exec
        # is safe.
        spec = importlib.util.spec_from_file_location("_gen_installer", str(out_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_seed_applied_when_no_existing_config(self, tmp_path, monkeypatch):
        seed = {
            "catalogues": [
                {"display_name": "studio", "path": "https://example.com/r.json"},
            ],
            "language": "ja",
            "auto_check_updates": False,
            "github_repo": "acme/carton",
            "proxy": "http://p:80",
        }
        mod = self._load_generated(tmp_path, monkeypatch, seed=seed)
        # InstallerProfile normalizes through CatalogueEntry; for HTTPS
        # paths the value round-trips unchanged so a direct equality
        # check is safe.
        assert mod.SEED_CONFIG == seed
        assert mod.CARTON_LANGUAGE == "ja"

    def test_no_seed_in_default_build(self, tmp_path, monkeypatch):
        mod = self._load_generated(tmp_path, monkeypatch, seed=None)
        assert mod.SEED_CONFIG is None


class TestRuntimeBuilderSubstitution:
    """The in-Maya "Build Installer" path must substitute every token.

    ``carton.core.installer_artifact`` is what the Profile Manager
    button calls. It used to carry its own copy of the substitution
    list, which silently fell behind the template when the bootstrap
    tokens were added: the button produced installers that raised
    ``NameError: name '__USERSETUP_HOOK_LITERAL__' is not defined`` the
    moment they were dropped onto Maya. The scan below is deliberately
    generic so a token added to the template in future fails here
    rather than on a user's machine.
    """

    def _build(self, tmp_path, **kwargs):
        from carton.core import installer_artifact
        out_path = tmp_path / "install_runtime.py"
        installer_artifact.build_one(str(out_path), version="9.9.9", **kwargs)
        return out_path.read_text(encoding="utf-8")

    def test_no_placeholder_survives(self, tmp_path):
        import re
        content = self._build(tmp_path)
        leftovers = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", content)))
        assert leftovers == [], "unsubstituted placeholders: {}".format(leftovers)

    def test_generated_installer_imports(self, tmp_path):
        content = self._build(tmp_path)
        out_path = tmp_path / "install_runtime.py"
        spec = importlib.util.spec_from_file_location(
            "_gen_runtime_installer", str(out_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.CARTON_VERSION == "9.9.9"
        # The bootstrap sources are inlined verbatim, not left as tokens.
        assert "def _apply_pending_update" in mod.BOOTSTRAP_PY
        assert "carton_bootstrap" in mod.USERSETUP_HOOK
        assert mod.USERSETUP_HOOK.startswith("\n")
        assert content.count("BOOTSTRAP_PY = ") == 1

    def test_both_builders_agree_on_the_bootstrap(self, tmp_path, monkeypatch):
        """The dev script and the runtime path ship the same bootstrap."""
        from carton.core import installer_artifact
        builder = _load_builder()
        monkeypatch.setattr(builder, "DIST_DIR", str(tmp_path))
        dev_path = tmp_path / "install_dev.py"
        builder.build(version="9.9.9", output=str(dev_path))

        runtime_path = tmp_path / "install_runtime.py"
        installer_artifact.build_one(str(runtime_path), version="9.9.9")

        def _literals(path):
            spec = importlib.util.spec_from_file_location(
                "_gen_" + path.stem, str(path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.BOOTSTRAP_PY, mod.USERSETUP_HOOK

        assert _literals(dev_path) == _literals(runtime_path)
