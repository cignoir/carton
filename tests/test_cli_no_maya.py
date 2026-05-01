"""Lock that the CLI entry point works without Maya being available.

The CLI is intended to run via ``uvx carton-maya`` in plain shells (no
Maya in sight), so importing ``carton.cli`` and invoking it must not
pull any ``maya.*`` module. Subprocess-driven so other tests in this
session that legitimately import maya stubs don't pollute the check.
"""

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
