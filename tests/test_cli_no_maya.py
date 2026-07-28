"""Lock that the CLI entry point works without Maya being available.

The CLI is intended to run via ``uvx carton-maya`` in plain shells (no
Maya in sight), so importing ``carton.cli`` and invoking it must not
pull any ``maya.*`` module. Subprocess-driven so other tests in this
session that legitimately import maya stubs don't pollute the check.
"""

import os
import subprocess
import sys


def test_carton_cli_imports_without_loading_maya():
    """``from carton.cli import main`` must not import any ``maya.*`` module."""
    code = (
        "import sys\n"
        "from carton.cli import main\n"
        "leaked = sorted(m for m in sys.modules if m == 'maya' or m.startswith('maya.'))\n"
        "assert not leaked, 'maya.* leaked into cli import: ' + ', '.join(leaked)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, "stderr=\n" + (result.stderr or "")


def test_python_m_carton_help_runs_without_maya():
    """``python -m carton --help`` must succeed without Maya available."""
    result = subprocess.run(
        [sys.executable, "-m", "carton", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, "stderr=\n" + (result.stderr or "")
    assert "carton-maya" in result.stdout


def test_python_m_carton_version_reports_the_package_version():
    """``--version`` is the first thing anyone runs against a CLI.

    It also has to agree with the installed package, so a release that
    stamps some version files and misses others shows up here.
    """
    import carton

    result = subprocess.run(
        [sys.executable, "-m", "carton", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, "stderr=\n" + (result.stderr or "")
    assert carton.__version__ in (result.stdout + result.stderr)


def test_carton_cli_help_does_not_load_maya():
    """Driving the parser past help text shouldn't pull maya.* either."""
    code = (
        "import sys\n"
        "sys.argv = ['carton-maya', '--help']\n"
        "try:\n"
        "    from carton.cli import main\n"
        "    main()\n"
        "except SystemExit:\n"
        "    pass\n"
        "leaked = sorted(m for m in sys.modules if m == 'maya' or m.startswith('maya.'))\n"
        "assert not leaked, 'maya.* leaked: ' + ', '.join(leaked)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, "stderr=\n" + (result.stderr or "")


def test_init_then_pack_e2e_without_maya(tmp_path):
    """End-to-end: ``package init`` scaffold lints clean and ``pack`` builds a zip."""
    workdir = tmp_path / "fresh_tool"
    init_result = subprocess.run(
        [
            sys.executable, "-m", "carton",
            "package", "init", str(workdir),
            "--non-interactive",
            "--type", "python_package",
            "--name", "fresh_tool",
            "--display-name", "Fresh Tool",
            "--version", "0.1.0",
            "--description", "scaffold smoke test",
            "--author", "tester",
            "--maya-versions", "2025,2026",
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert init_result.returncode == 0, init_result.stderr
    assert (workdir / "package.json").is_file()
    assert (workdir / "fresh_tool" / "__init__.py").is_file()

    check_result = subprocess.run(
        [sys.executable, "-m", "carton", "package", "check", str(workdir)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert check_result.returncode == 0, check_result.stderr

    pack_result = subprocess.run(
        [
            sys.executable, "-m", "carton",
            "package", "pack", str(workdir),
            "--out", str(tmp_path / "dist"),
        ],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert pack_result.returncode == 0, pack_result.stderr
    assert (tmp_path / "dist" / "fresh_tool-0.1.0.zip").is_file()
