"""Tests for ``carton.core.bundle`` (CLI ``package bundle``)."""

import ast
import json
import os

import pytest

from carton.core.bundle import (
    BundleError, bundle_package, build_source, plan_bundle,
)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def _pkg_json(folder, **overrides):
    base = {
        "name": "my_tool",
        "display_name": "My Tool",
        "version": "1.2.3",
        "description": "a tool",
        "author": "tester",
        "maya_versions": ["2025"],
        "type": "python_package",
        "entry_point": {
            "type": "python", "module": "my_tool", "function": "show",
        },
    }
    base.update(overrides)
    _write(os.path.join(folder, "package.json"), json.dumps(base))


def _minimal(folder, **overrides):
    """A package shaped like the generators this was written for."""
    _pkg_json(folder, **overrides)
    _write(os.path.join(folder, "my_tool/__init__.py"), (
        '"""My Tool.\n'
        "\n"
        "    import my_tool\n"           # a usage example, not an import
        "    my_tool.show()\n"
        '"""\n'
        "\n"
        '__version__ = "1.2.3"\n'
        "\n"
        "\n"
        "def show():\n"
        "    from my_tool.ui import make_window\n"
        "    return make_window(TITLE)\n"
    ))
    _write(os.path.join(folder, "my_tool/core/__init__.py"),
           '"""Re-export shim."""\n\nfrom .maths import add\n\n__all__ = ["add"]\n')
    _write(os.path.join(folder, "my_tool/core/maths.py"),
           "from __future__ import annotations\n\nimport math\n\n"
           "TITLE = 'My Tool'\n\n\ndef add(a, b):\n    return a + b\n")
    _write(os.path.join(folder, "my_tool/ui.py"), (
        "from .core.maths import add\n"
        "from . import theme\n"
        "\n"
        "\n"
        "def make_window(title):\n"
        "    return (title, theme.COLOR, add(1, 2))\n"
    ))
    _write(os.path.join(folder, "my_tool/theme.py"), 'COLOR = "#123456"\n')


def _run(src):
    ns = {"__name__": "my_tool_standalone"}
    exec(compile(src, "<bundle>", "exec"), ns)
    return ns


# ---------------------------------------------------------------------------
#  The happy path
# ---------------------------------------------------------------------------
def test_bundle_runs_and_exposes_the_entry_point(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    ns = _run(build_source(folder))
    assert ns["show"]() == ("My Tool", "#123456", 3)


def test_output_lands_beside_the_package_and_is_named_for_it(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    path = bundle_package(folder)
    assert os.path.basename(path) == "my_tool_standalone.py"
    assert os.path.dirname(path) == os.path.abspath(folder)


def test_no_package_imports_survive(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    # Ask the parse, not the text: a usage example inside a docstring reads
    # exactly like an import and is supposed to stay.
    tree = ast.parse(build_source(folder))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not node.level, ast.dump(node)
            assert not (node.module or "").startswith("my_tool")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("my_tool")


def test_a_usage_example_in_a_docstring_is_left_alone(tmp_path):
    # The example reads `import my_tool`; stripping it by text would gut the
    # docstring, so removal has to come from the parse.
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    assert "    import my_tool\n" in build_source(folder)


def test_module_references_still_resolve(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    ns = _run(build_source(folder))
    assert ns["theme"].COLOR == "#123456"
    with pytest.raises(AttributeError):
        ns["theme"].nope


def test_shim_packages_contribute_nothing_but_ordering(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    order, _infos, problems, _meta, pkg, function = plan_bundle(folder)
    assert problems == []
    assert pkg == "my_tool" and function == "show"
    assert "my_tool.core" not in order          # the re-export shim is dropped
    assert order.index("my_tool.core.maths") < order.index("my_tool.ui")
    assert order[-1] == "my_tool"               # entry point reads last


# ---------------------------------------------------------------------------
#  What it refuses
# ---------------------------------------------------------------------------
def test_duplicate_top_level_names_are_refused(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    _write(os.path.join(folder, "my_tool/theme.py"),
           'COLOR = "#123456"\nTITLE = "clash"\n')
    _order, _infos, problems, _m, _p, _f = plan_bundle(folder)
    assert any("TITLE" in p for p in problems)
    with pytest.raises(BundleError) as exc:
        build_source(folder)
    assert "TITLE" in str(exc.value)


def test_a_name_that_is_also_a_module_is_refused(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    _write(os.path.join(folder, "my_tool/core/maths.py"),
           "TITLE = 'My Tool'\n\n\ndef add(a, b):\n    return a + b\n\n\n"
           "def theme():\n    return 1\n")
    _order, _infos, problems, _m, _p, _f = plan_bundle(folder)
    assert any("theme" in p and "module" in p for p in problems)


def test_a_real_import_cycle_is_refused(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    _write(os.path.join(folder, "my_tool/theme.py"),
           "from .ui import make_window\n\nCOLOR = '#123456'\n")
    with pytest.raises(BundleError) as exc:
        plan_bundle(folder)
    assert "circular" in str(exc.value)


def test_a_lazy_self_import_is_not_a_cycle(tmp_path):
    # my_tool/__init__ imports ui inside show(), and ui may point back at the
    # package for its version — that runs after the file is fully defined.
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    _write(os.path.join(folder, "my_tool/ui.py"), (
        "from .core.maths import add\n"
        "from . import theme\n"
        "\n"
        "\n"
        "def make_window(title):\n"
        "    from my_tool import __version__\n"
        "    return (title, theme.COLOR, add(1, 2), __version__)\n"
    ))
    ns = _run(build_source(folder))
    assert ns["show"]() == ("My Tool", "#123456", 3, "1.2.3")


def test_only_python_packages_can_be_bundled(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder, type="mel_script")
    with pytest.raises(BundleError) as exc:
        plan_bundle(folder)
    assert "python_package" in str(exc.value)


def test_a_missing_package_json_is_reported(tmp_path):
    folder = str(tmp_path / "pkg")
    os.makedirs(folder)
    with pytest.raises(BundleError) as exc:
        plan_bundle(folder)
    assert "package.json" in str(exc.value)


# ---------------------------------------------------------------------------
#  What it leaves out
# ---------------------------------------------------------------------------
def test_modules_nothing_imports_stay_out(tmp_path):
    # A Maya plugin cannot live inside a Script Editor paste, and nothing
    # imports it, so it should simply not be folded in.
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    _write(os.path.join(folder, "my_tool/plugins/cmd.py"),
           "TITLE = 'clashes but is unreachable'\n")
    order, _infos, problems, _m, _p, _f = plan_bundle(folder)
    assert problems == []
    assert not any("plugins" in m for m in order)


def test_maya_imports_do_not_stop_it_loading_outside_maya(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    _write(os.path.join(folder, "my_tool/theme.py"),
           "import maya.cmds as cmds\n\nCOLOR = '#123456'\n")
    ns = _run(build_source(folder))          # no Maya here, must still load
    assert ns["cmds"] is None
    assert ns["show"]() == ("My Tool", "#123456", 3)


# ---------------------------------------------------------------------------
#  Staying current
# ---------------------------------------------------------------------------
def test_check_passes_for_a_freshly_built_file(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    path = bundle_package(folder)
    assert bundle_package(folder, check=True) == path


def test_check_fails_once_the_package_moves_on(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    bundle_package(folder)
    _write(os.path.join(folder, "my_tool/theme.py"), 'COLOR = "#ffffff"\n')
    with pytest.raises(BundleError) as exc:
        bundle_package(folder, check=True)
    assert "out of date" in str(exc.value)


def test_check_before_anything_was_built(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    with pytest.raises(BundleError) as exc:
        bundle_package(folder, check=True)
    assert "not been built" in str(exc.value)


def test_the_header_carries_the_package_metadata(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    src = build_source(folder)
    assert "My Tool 1.2.3" in src
    assert "a tool" in src
    assert "tool.show()" in src


# ---------------------------------------------------------------------------
#  Data files
# ---------------------------------------------------------------------------
def test_declared_data_travels_with_the_bundle(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder, bundle={"data": ["data/*.json"]})
    _write(os.path.join(folder, "my_tool/data/one.json"), '{"id": "one"}')
    _write(os.path.join(folder, "my_tool/data/two.json"), '{"id": "日本"}')
    ns = _run(build_source(folder))
    assert sorted(ns["BUNDLED_DATA"]) == ["data/one.json", "data/two.json"]
    assert json.loads(ns["BUNDLED_DATA"]["data/two.json"])["id"] == "日本"


def test_embedded_data_is_escaped_to_ascii(tmp_path):
    # A build that survives a paste through a console on a non-UTF-8 locale
    # cannot carry raw non-ASCII in the data it embeds.
    folder = str(tmp_path / "pkg")
    _minimal(folder, bundle={"data": ["data/*.json"]})
    _write(os.path.join(folder, "my_tool/data/one.json"), '{"label": "矢"}')
    src = build_source(folder)
    line = [x for x in src.split("\n") if "data/one.json" in x and ":" in x][0]
    assert "\\u77e2" in line        # the escape, spelled out
    assert "矢" not in line
    assert line.isascii()


def test_no_data_declared_means_no_data_block(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    ns = _run(build_source(folder))
    assert "BUNDLED_DATA" not in ns


def test_a_data_pattern_that_matches_nothing_is_an_error(tmp_path):
    folder = str(tmp_path / "pkg")
    _minimal(folder, bundle={"data": ["presets/*.json"]})
    with pytest.raises(BundleError) as exc:
        build_source(folder)
    assert "matched nothing" in str(exc.value)


# ---------------------------------------------------------------------------
#  __file__
# ---------------------------------------------------------------------------
def test_reading_dunder_file_at_import_is_refused(tmp_path):
    # A single file has no folder beside it, and pasted into the Script Editor
    # it has no __file__ at all — this would die the moment it loads.
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    _write(os.path.join(folder, "my_tool/theme.py"),
           "import os\n\nHERE = os.path.dirname(__file__)\nCOLOR = '#123456'\n")
    _order, _infos, problems, _m, _p, _f = plan_bundle(folder)
    assert any("__file__" in p and "theme.py" in p for p in problems)


def test_reading_dunder_file_inside_a_function_is_allowed(tmp_path):
    # Guarding for its absence is the package's own business, and the ones
    # that do should not be blocked.
    folder = str(tmp_path / "pkg")
    _minimal(folder)
    _write(os.path.join(folder, "my_tool/theme.py"), (
        "import os\n"
        "\n"
        "COLOR = '#123456'\n"
        "\n"
        "\n"
        "def here():\n"
        "    try:\n"
        "        return os.path.dirname(__file__)\n"
        "    except NameError:\n"
        "        return None\n"
    ))
    ns = _run(build_source(folder))
    assert ns["here"]() is None
