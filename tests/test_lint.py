"""Tests for ``carton.core.lint``."""

import json
import os

import pytest

from carton.core.lint import (
    SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO,
    LintResult, lint_package,
)


def _write(path, content):
    """Write text to ``path``, creating parents as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _write_pkg_json(folder, **fields):
    base = {
        "name": "my_tool",
        "display_name": "My Tool",
        "version": "1.0.0",
        "description": "test",
        "author": "tester",
        "maya_versions": ["2025"],
        "type": "python_package",
        "entry_point": {
            "type": "python", "module": "my_tool", "function": "show",
        },
    }
    base.update(fields)
    path = os.path.join(folder, "package.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(base, f)
    return path


# ---------------------------------------------------------------------------
# Path handling
# ---------------------------------------------------------------------------

def test_lint_nonexistent_path_returns_error():
    result = lint_package("/nonexistent/path/abc123")
    assert result.has_errors()
    assert result.errors[0].rule == "path_not_found"


# ---------------------------------------------------------------------------
# Folder lint - no package.json
# ---------------------------------------------------------------------------

def test_lint_folder_without_package_json_warns(tmp_path):
    _write(str(tmp_path / "tool" / "__init__.py"), "def show(): pass\n")
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.issues}
    assert "package_json_missing" in rules
    assert "auto_detected_type" in rules
    assert not result.has_errors()


def test_lint_folder_with_devkits_emits_vendor_warning(tmp_path):
    """Recreates the exattr-maya scenario — devkits at root should warn."""
    _write(str(tmp_path / "devkits" / "Maya2025" / "fake.py"), "")
    _write(str(tmp_path / "src" / "tool.cpp"), "")
    _write(str(tmp_path / "dist" / "my-tool-2025.mll"), "")

    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.issues}
    assert "vendor_dirs" in rules

    vendor_issue = [i for i in result.issues if i.rule == "vendor_dirs"][0]
    assert vendor_issue.severity == SEVERITY_WARNING
    assert "devkits" in vendor_issue.message
    assert "dist" in vendor_issue.message


# ---------------------------------------------------------------------------
# Folder lint - with valid package.json
# ---------------------------------------------------------------------------

def test_lint_valid_python_package(tmp_path):
    """A well-formed python_package should produce no errors."""
    _write_pkg_json(str(tmp_path))
    _write(str(tmp_path / "my_tool" / "__init__.py"), "def show(): pass\n")
    result = lint_package(str(tmp_path))
    assert not result.has_errors(), [
        (i.rule, i.message) for i in result.issues
    ]


def test_lint_python_module_missing_init_py(tmp_path):
    """entry_point.module without matching __init__.py should error."""
    _write_pkg_json(str(tmp_path), entry_point={
        "type": "python", "module": "missing_module", "function": "show",
    })
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.errors}
    assert "entry_point_module_missing" in rules


# ---------------------------------------------------------------------------
# Plugin platform requirement
# ---------------------------------------------------------------------------

def test_lint_plugin_without_platform_errors(tmp_path):
    _write_pkg_json(
        str(tmp_path),
        type="plugin",
        entry_point={
            "type": "plugin",
            "plugin_file": "myPlugin",
        },
    )
    _write(str(tmp_path / "plug-ins" / "myPlugin.mll"), "")
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.errors}
    assert "plugin_platform_required" in rules


def test_lint_plugin_with_platform_passes(tmp_path):
    _write_pkg_json(
        str(tmp_path),
        type="plugin",
        platform=["win64"],
        entry_point={
            "type": "plugin",
            "plugin_file": "myPlugin",
        },
    )
    _write(str(tmp_path / "plug-ins" / "myPlugin.mll"), "")
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.errors}
    assert "plugin_platform_required" not in rules


def test_lint_exec_entry_point_passes_schema(tmp_path):
    """exec is a first-class launch type — the schema must accept it.

    Regression guard: GUI single-file registrations emit
    ``{"type": "exec", "file": ...}`` and publish injects it verbatim
    into the canonical package.json, but the schema's oneOf historically
    lacked an exec variant, so lint flagged Carton's own output.
    """
    _write_pkg_json(
        str(tmp_path),
        entry_point={"type": "exec", "file": "create_sphere.py"},
    )
    _write(str(tmp_path / "create_sphere.py"), "print('hi')\n")
    result = lint_package(str(tmp_path))
    assert not result.has_errors(), [
        (i.rule, i.message) for i in result.errors
    ]


def test_lint_plugin_command_passes_schema(tmp_path):
    """Optional post-load ``command`` (single-file dialect) is schema-legal."""
    _write_pkg_json(
        str(tmp_path),
        type="plugin",
        platform=["win64"],
        entry_point={
            "type": "plugin",
            "plugin_file": "myPlugin",
            "command": "import my_tool; my_tool.show()",
        },
    )
    _write(str(tmp_path / "plug-ins" / "myPlugin.mll"), "")
    result = lint_package(str(tmp_path))
    assert not result.has_errors(), [
        (i.rule, i.message) for i in result.errors
    ]


def test_lint_plugin_missing_mll_file_errors(tmp_path):
    _write_pkg_json(
        str(tmp_path),
        type="plugin",
        platform=["win64"],
        entry_point={
            "type": "plugin",
            "plugin_file": "missingPlugin",
        },
    )
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.errors}
    assert "entry_point_plugin_missing" in rules


# ---------------------------------------------------------------------------
# Maya module
# ---------------------------------------------------------------------------

def test_lint_maya_module_with_valid_mod(tmp_path):
    mod_content = (
        "+ MAYAVERSION:2025 PLATFORM:win64 my-plugin 1.0.0 .\n"
        "plug-ins: plug-ins/2025/win64\n"
    )
    _write(str(tmp_path / "my-plugin.mod"), mod_content)
    _write(str(tmp_path / "plug-ins" / "2025" / "win64" / "my-plugin.mll"), "")

    result = lint_package(str(tmp_path))
    assert not result.has_errors(), [
        (i.rule, i.message) for i in result.issues
    ]


def test_lint_maya_module_mod_without_mayaversion_warns(tmp_path):
    """A '+' block without MAYAVERSION: should warn (cross-version risk)."""
    mod_content = (
        "+ my-plugin 1.0.0 .\n"
        "plug-ins: plug-ins\n"
    )
    _write(str(tmp_path / "my-plugin.mod"), mod_content)

    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.warnings}
    assert "mod_no_mayaversion" in rules


def test_lint_maya_module_type_without_mod_errors(tmp_path):
    """type=maya_module declared in package.json but no .mod file."""
    _write_pkg_json(
        str(tmp_path),
        type="maya_module",
        entry_point={},
    )
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.errors}
    assert "module_marker_missing" in rules


# ---------------------------------------------------------------------------
# Schema validation (jsonschema-driven)
# ---------------------------------------------------------------------------

def test_lint_invalid_version_format_errors(tmp_path):
    _write_pkg_json(str(tmp_path), version="not-a-semver")
    _write(str(tmp_path / "my_tool" / "__init__.py"), "def show(): pass\n")
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.errors}
    assert "schema" in rules


def test_lint_missing_required_field_errors(tmp_path):
    """Skipping a required field should be caught by schema validation."""
    pkg = {
        "name": "my_tool",
        "version": "1.0.0",
        "type": "python_package",
        "entry_point": {
            "type": "python", "module": "my_tool", "function": "show",
        },
        # missing display_name, description, author, maya_versions
    }
    with open(os.path.join(str(tmp_path), "package.json"), "w", encoding="utf-8") as f:
        json.dump(pkg, f)
    result = lint_package(str(tmp_path))
    assert result.has_errors()
    assert any(i.rule == "schema" for i in result.errors)


def test_lint_malformed_package_json_errors(tmp_path):
    _write(str(tmp_path / "package.json"), "{not json")
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.errors}
    assert "package_json_syntax" in rules


# ---------------------------------------------------------------------------
# Icon path
# ---------------------------------------------------------------------------

def test_lint_missing_icon_path_errors(tmp_path):
    _write_pkg_json(str(tmp_path), icon="resources/icon.png")
    _write(str(tmp_path / "my_tool" / "__init__.py"), "def show(): pass\n")
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.errors}
    assert "icon_missing" in rules


def test_lint_emoji_icon_passes(tmp_path):
    _write_pkg_json(str(tmp_path), icon="🔧")
    _write(str(tmp_path / "my_tool" / "__init__.py"), "def show(): pass\n")
    result = lint_package(str(tmp_path))
    rules = {i.rule for i in result.errors}
    assert "icon_missing" not in rules


# ---------------------------------------------------------------------------
# Single-file lint
# ---------------------------------------------------------------------------

def test_lint_single_py_without_sidecar_warns(tmp_path):
    py = str(tmp_path / "tool.py")
    _write(py, "def show(): pass\n")
    result = lint_package(py)
    rules = {i.rule for i in result.warnings}
    assert "sidecar_missing" in rules


def test_lint_single_py_with_sidecar_passes(tmp_path):
    py = str(tmp_path / "tool.py")
    sidecar = py + ".carton.json"
    _write(py, "def show(): pass\n")
    # Place __init__.py so the python entry_point resolves
    _write(str(tmp_path / "tool" / "__init__.py"), "def show(): pass\n")
    sidecar_data = {
        "name": "tool",
        "display_name": "Tool",
        "version": "1.0.0",
        "description": "test",
        "author": "tester",
        "maya_versions": ["2025"],
        "type": "python_package",
        "entry_point": {"type": "python", "module": "tool", "function": "show"},
    }
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(sidecar_data, f)
    result = lint_package(py)
    assert not result.has_errors(), [
        (i.rule, i.message) for i in result.issues
    ]
