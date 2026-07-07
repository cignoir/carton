"""Tests for scripts/bump_version.py — the trio must move together.

Regression guard: the 0.5.6/0.5.8 divergence happened because a bump
touched only two of the three version-bearing files. test_version_sync
catches the aftermath; this pins the tool that is supposed to prevent
it in the first place.
"""

import importlib.util
import json
import os

import pytest


def _load_script():
    path = os.path.join(os.path.dirname(__file__), os.pardir,
                        "scripts", "bump_version.py")
    spec = importlib.util.spec_from_file_location("bump_version_ut",
                                                  os.path.abspath(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the script's module-level paths at a throwaway trio."""
    pkg = tmp_path / "package.json"
    init = tmp_path / "__init__.py"
    pyproject = tmp_path / "pyproject.toml"
    pkg.write_text('{\n  "version": "0.5.8"\n}\n', encoding="utf-8")
    init.write_text('__version__ = "0.5.8"\nprint(__version__)\n',
                    encoding="utf-8")
    pyproject.write_text(
        '[project]\nname = "carton-maya"\nversion = "0.5.8"\n',
        encoding="utf-8")

    script = _load_script()
    monkeypatch.setattr(script, "_PKG_PATH", str(pkg))
    monkeypatch.setattr(script, "_INIT_PATH", str(init))
    monkeypatch.setattr(script, "_PYPROJECT_PATH", str(pyproject))
    return script, pkg, init, pyproject


def _versions(pkg, init, pyproject):
    return (
        json.loads(pkg.read_text(encoding="utf-8"))["version"],
        init.read_text(encoding="utf-8"),
        pyproject.read_text(encoding="utf-8"),
    )


def test_patch_bumps_all_three_files(sandbox):
    script, pkg, init, pyproject = sandbox
    assert script.bump("patch") == "0.5.9"
    v_pkg, init_text, pyproject_text = _versions(pkg, init, pyproject)
    assert v_pkg == "0.5.9"
    assert '__version__ = "0.5.9"' in init_text
    assert 'version = "0.5.9"' in pyproject_text


def test_minor_and_major_reset_lower_components(sandbox):
    script, pkg, _, _ = sandbox
    assert script.bump("minor") == "0.6.0"
    assert script.bump("major") == "1.0.0"


def test_explicit_version(sandbox):
    script, pkg, init, pyproject = sandbox
    assert script.bump("2.3.4") == "2.3.4"
    v_pkg, init_text, pyproject_text = _versions(pkg, init, pyproject)
    assert v_pkg == "2.3.4"
    assert '__version__ = "2.3.4"' in init_text
    assert 'version = "2.3.4"' in pyproject_text


def test_only_first_version_line_is_touched(sandbox):
    """pyproject may contain other version-ish lines (requires-python
    etc.) — only the [project] version line may change."""
    script, _, init, _ = sandbox
    script.bump("patch")
    # The print(__version__) line in __init__ must survive untouched.
    assert "print(__version__)" in init.read_text(encoding="utf-8")
