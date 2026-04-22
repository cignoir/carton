"""Unit tests for :mod:`carton.core._publisher_zip`.

The helper used to live on ``Publisher`` so exercising it required
setting up a full :class:`~carton.core.config.Config`; now it takes
``staging_dir`` as a plain argument, and these tests only touch the
filesystem. Covers:

* Folder-mode walks respect the VCS / build exclusion set
* ``.pyc`` stripping honours ``include_compiled``
* An inherited ``package.json`` at the source root is replaced with
  the canonical bytes we inject
* ``embed_source_path=False`` omits the ``source_path`` field
* File-mode packages land as a single-file zip with injected manifest
"""

import json
import os
import zipfile

import pytest

from carton.core._publisher_zip import create_zip


def _read_pkg_json(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read("package.json").decode("utf-8"))


def _names(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return set(zf.namelist())


def _build_args(local_path, tmp_path, **overrides):
    args = dict(
        staging_dir=str(tmp_path / "staging"),
        local_path=str(local_path),
        namespace="ns",
        name="pkg",
        version="1.0.0",
        is_folder=True,
        entry_point={},
        display_name="Package",
        icon="",
        description="desc",
        pkg_type="python_package",
        author="me",
    )
    args.update(overrides)
    return args


def test_folder_mode_includes_sources_and_injects_manifest(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "tool.py").write_text("print('hi')\n")

    zp = create_zip(**_build_args(src, tmp_path))

    names = _names(zp)
    assert "__init__.py" in names
    assert "tool.py" in names
    assert "package.json" in names

    manifest = _read_pkg_json(zp)
    assert manifest["namespace"] == "ns"
    assert manifest["name"] == "pkg"
    assert manifest["version"] == "1.0.0"
    assert manifest["source_path"] == os.path.abspath(str(src))


def test_folder_mode_excludes_vcs_and_build_dirs(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "keep.py").write_text("")
    for bad in ("__pycache__", ".git", "tests", "dist", ".vscode"):
        (src / bad).mkdir()
        (src / bad / "inner.py").write_text("")

    zp = create_zip(**_build_args(src, tmp_path))

    names = _names(zp)
    assert "keep.py" in names
    for bad in ("__pycache__", ".git", "tests", "dist", ".vscode"):
        assert not any(n.startswith(bad + "/") or n.startswith(bad + "\\")
                       for n in names), "{} leaked into zip".format(bad)


def test_pyc_stripped_when_sibling_py_exists(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("")
    (src / "mod.pyc").write_bytes(b"\x00compiled")
    (src / "standalone.pyc").write_bytes(b"\x00compiled")

    zp = create_zip(**_build_args(src, tmp_path))

    names = _names(zp)
    assert "mod.py" in names
    assert "mod.pyc" not in names  # has a .py sibling → stripped
    assert "standalone.pyc" in names  # no .py sibling → kept


def test_include_compiled_keeps_all_pyc(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("")
    (src / "mod.pyc").write_bytes(b"\x00")

    zp = create_zip(**_build_args(src, tmp_path, include_compiled=True))

    names = _names(zp)
    assert "mod.py" in names
    assert "mod.pyc" in names


def test_inherited_package_json_at_root_is_replaced(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "package.json").write_text('{"legacy": true}')

    zp = create_zip(**_build_args(src, tmp_path))

    # Only one package.json in the zip, and it's the injected one.
    manifest = _read_pkg_json(zp)
    assert "legacy" not in manifest
    assert manifest["namespace"] == "ns"


def test_embed_source_path_false_omits_source_path(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.py").write_text("")

    zp = create_zip(**_build_args(src, tmp_path, embed_source_path=False))

    manifest = _read_pkg_json(zp)
    assert "source_path" not in manifest


def test_home_origin_is_embedded_when_provided(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "x.py").write_text("")
    home = {"type": "github", "repo": "acme/foo"}

    zp = create_zip(**_build_args(src, tmp_path, home_origin=home))

    manifest = _read_pkg_json(zp)
    assert manifest["home_origin"] == home


def test_file_mode_produces_single_file_zip(tmp_path):
    src_file = tmp_path / "standalone.py"
    src_file.write_text("print('single')\n")

    zp = create_zip(**_build_args(src_file, tmp_path, is_folder=False))

    names = _names(zp)
    assert names == {"standalone.py", "package.json"}
    manifest = _read_pkg_json(zp)
    assert manifest["name"] == "pkg"
