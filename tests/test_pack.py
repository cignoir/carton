"""Tests for ``carton.core.pack`` (CLI ``package pack``)."""

import json
import os
import zipfile

import pytest

from carton.core.pack import pack_package, PackError


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _write_pkg(folder, **overrides):
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
    base.update(overrides)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "package.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(base, f)
    return path


def _names(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return set(zf.namelist())


def test_pack_minimal_python_package(tmp_path):
    src = tmp_path / "src"
    _write_pkg(str(src))
    _write(str(src / "my_tool" / "__init__.py"), "def show(): pass\n")

    zip_path = pack_package(str(src), out_dir=str(tmp_path / "dist"))

    assert os.path.basename(zip_path) == "my_tool-1.0.0.zip"
    names = _names(zip_path)
    assert "package.json" in names
    assert "my_tool/__init__.py" in names


def test_pack_drops_excluded_dirs(tmp_path):
    src = tmp_path / "src"
    _write_pkg(str(src))
    _write(str(src / "my_tool" / "__init__.py"), "def show(): pass\n")
    _write(str(src / "__pycache__" / "x.pyc"), "")
    _write(str(src / ".git" / "config"), "")
    _write(str(src / "tests" / "test_x.py"), "")

    zip_path = pack_package(str(src), out_dir=str(tmp_path / "dist"))
    names = _names(zip_path)
    assert not any(n.startswith("__pycache__/") for n in names)
    assert not any(n.startswith(".git/") for n in names)
    assert not any(n.startswith("tests/") for n in names)


def test_pack_strips_pyc_with_py_sibling(tmp_path):
    src = tmp_path / "src"
    _write_pkg(str(src))
    _write(str(src / "my_tool" / "__init__.py"), "def show(): pass\n")
    _write(str(src / "my_tool" / "x.py"), "")
    _write(str(src / "my_tool" / "x.pyc"), "")

    zip_path = pack_package(str(src), out_dir=str(tmp_path / "dist"))
    names = _names(zip_path)
    assert "my_tool/x.py" in names
    assert "my_tool/x.pyc" not in names


def test_pack_keeps_pyc_when_include_compiled(tmp_path):
    src = tmp_path / "src"
    _write_pkg(str(src))
    _write(str(src / "my_tool" / "__init__.py"), "")
    _write(str(src / "my_tool" / "x.py"), "")
    _write(str(src / "my_tool" / "x.pyc"), "")

    zip_path = pack_package(
        str(src), out_dir=str(tmp_path / "dist"), include_compiled=True,
    )
    names = _names(zip_path)
    assert "my_tool/x.pyc" in names


def test_pack_validates_by_default(tmp_path):
    src = tmp_path / "src"
    # Missing entry_point module folder = lint error
    _write_pkg(str(src))
    # No my_tool/__init__.py created → entry_point_module_missing error

    with pytest.raises(PackError, match="lint errors"):
        pack_package(str(src), out_dir=str(tmp_path / "dist"))


def test_pack_no_validate_skips_lint(tmp_path):
    src = tmp_path / "src"
    _write_pkg(str(src))
    # Still no entry_point module — but we skip validation
    zip_path = pack_package(
        str(src), out_dir=str(tmp_path / "dist"), validate=False,
    )
    assert os.path.isfile(zip_path)


def test_pack_missing_package_json_raises(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    with pytest.raises(PackError, match="package.json not found"):
        pack_package(str(src), out_dir=str(tmp_path / "dist"))


def test_pack_does_not_zip_itself(tmp_path):
    src = tmp_path / "src"
    _write_pkg(str(src))
    _write(str(src / "my_tool" / "__init__.py"), "def show(): pass\n")

    # Output dir sits inside src — pack should still skip the zip itself
    out_dir = src / "dist"
    zip_path = pack_package(str(src), out_dir=str(out_dir))

    names = _names(zip_path)
    assert not any(n.endswith("my_tool-1.0.0.zip") for n in names)


def test_pack_preserves_package_json_verbatim(tmp_path):
    """Pack must NOT rewrite package.json — author's file is the SoT."""
    src = tmp_path / "src"
    pkg_path = _write_pkg(str(src), namespace="myteam")
    _write(str(src / "my_tool" / "__init__.py"), "def show(): pass\n")

    zip_path = pack_package(str(src), out_dir=str(tmp_path / "dist"))

    with zipfile.ZipFile(zip_path) as zf:
        packed = json.loads(zf.read("package.json").decode("utf-8"))
    with open(pkg_path, "r", encoding="utf-8") as f:
        original = json.load(f)
    assert packed == original
