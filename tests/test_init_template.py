"""Tests for ``carton.core.init_template`` (CLI ``package init``)."""

import json
import os

import pytest

from carton.core.init_template import (
    InitError,
    PACKAGE_TYPES,
    build_context,
    render_template,
    template_root,
)


def test_template_roots_exist_for_all_types():
    for pkg_type in PACKAGE_TYPES:
        root = template_root(pkg_type)
        assert os.path.isdir(root)
        assert os.path.isfile(os.path.join(root, "package.json"))


def test_template_root_rejects_unknown_type():
    with pytest.raises(InitError, match="unknown package type"):
        template_root("ruby_gem")


def test_render_python_package(tmp_path):
    target = tmp_path / "my_tool"
    ctx = build_context(
        name="my_tool", display_name="My Tool", version="0.1.0",
        description="A tool", author="me", maya_versions=["2025", "2026"],
    )
    render_template("python_package", str(target), ctx)

    pkg_json = target / "package.json"
    assert pkg_json.is_file()
    pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
    assert pkg["name"] == "my_tool"
    assert pkg["display_name"] == "My Tool"
    assert pkg["version"] == "0.1.0"
    assert pkg["maya_versions"] == ["2025", "2026"]
    assert pkg["type"] == "python_package"
    assert pkg["entry_point"]["module"] == "my_tool"

    init_py = target / "my_tool" / "__init__.py"
    assert init_py.is_file()
    body = init_py.read_text(encoding="utf-8")
    assert "{{" not in body  # all placeholders substituted
    assert "my_tool" in body


def test_render_mel_script(tmp_path):
    target = tmp_path / "my_mel"
    ctx = build_context(
        name="my_mel", display_name="My Mel", version="0.1.0",
        description="m", author="a", maya_versions=["2025"],
    )
    render_template("mel_script", str(target), ctx)

    pkg = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert pkg["entry_point"]["script"] == "my_mel.mel"
    mel_file = target / "scripts" / "my_mel.mel"
    assert mel_file.is_file()


def test_render_plugin_includes_platform(tmp_path):
    target = tmp_path / "my_plugin"
    ctx = build_context(
        name="my_plugin", display_name="My Plugin", version="0.1.0",
        description="p", author="a", maya_versions=["2025"],
        platform=["win64", "linux"],
    )
    render_template("plugin", str(target), ctx)

    pkg = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert pkg["platform"] == ["win64", "linux"]
    assert (target / "plug-ins" / "my_plugin.py").is_file()


def test_render_maya_module(tmp_path):
    target = tmp_path / "my_mod"
    ctx = build_context(
        name="my_mod", display_name="My Mod", version="0.1.0",
        description="m", author="a", maya_versions=["2025"],
    )
    render_template("maya_module", str(target), ctx)

    assert (target / "package.json").is_file()
    assert (target / "my_mod.mod").is_file()
    mod_text = (target / "my_mod.mod").read_text(encoding="utf-8")
    assert "my_mod" in mod_text
    assert "0.1.0" in mod_text


def test_render_refuses_nonempty_target(tmp_path):
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "existing.txt").write_text("hi", encoding="utf-8")

    ctx = build_context(
        name="x", display_name="X", version="0.1.0",
        description="", author="", maya_versions=["2025"],
    )
    with pytest.raises(InitError, match="not empty"):
        render_template("python_package", str(target), ctx)


def test_render_force_allows_overwrite(tmp_path):
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "existing.txt").write_text("hi", encoding="utf-8")

    ctx = build_context(
        name="x", display_name="X", version="0.1.0",
        description="", author="", maya_versions=["2025"],
    )
    written = render_template("python_package", str(target), ctx, force=True)
    assert (target / "package.json").is_file()
    assert (target / "existing.txt").is_file()  # untouched
    assert any(p.endswith("package.json") for p in written)


def test_rendered_python_package_passes_lint(tmp_path):
    """End-to-end: a fresh init scaffold should lint clean (errors == 0)."""
    from carton.core.lint import lint_package

    target = tmp_path / "fresh"
    ctx = build_context(
        name="fresh", display_name="Fresh", version="0.1.0",
        description="d", author="a", maya_versions=["2025"],
    )
    render_template("python_package", str(target), ctx)

    result = lint_package(str(target))
    assert not result.has_errors(), [
        (i.rule, i.message) for i in result.errors
    ]
