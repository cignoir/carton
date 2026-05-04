"""Carton development reload script.

Run the following in Maya's Script Editor:
    exec(open(r"G:\\workspace\\carton\\scripts\\dev_reload.py", encoding="utf-8").read())
"""

import os
import shutil
import sys

_SRC = r"G:\workspace\carton\carton"
_BOOTSTRAP_DIR = os.path.expanduser("~/Documents/maya/carton")
_DST = os.path.join(_BOOTSTRAP_DIR, "carton")


def reload_carton():
    # Bail out before any destructive step if the dev source tree isn't
    # where we think it is — the previous version rmtree'd _DST first and
    # then failed at copytree, leaving the deployed package missing.
    if not os.path.isdir(_SRC):
        raise RuntimeError(
            "[dev_reload] Source tree not found: {}\n"
            "Update _SRC at the top of this script to point at your local"
            " carton/ checkout before running again."
            .format(_SRC)
        )

    # 1. Close the window. ``QWidget.close()`` hides the widget but
    # MayaQWidgetDockableMixin leaves the surrounding workspaceControl
    # alive — Maya keeps the dock slot around for re-attach. After we
    # clear sys.modules and re-show, the new CartonWindow tries to
    # register a workspaceControl with the same name and Maya rejects
    # it ("object name '...' is not unique"). Delete the control here
    # so the next show() starts from a clean slate.
    if "carton" in sys.modules:
        import carton
        if carton._window is not None:
            try:
                carton._window.close()
            except Exception:
                pass
    try:
        import maya.cmds as cmds
        for ctl in ("CartonWindowWorkspaceControl",):
            if cmds.workspaceControl(ctl, exists=True):
                cmds.deleteUI(ctl)
    except ImportError:
        pass

    # 2. Clear module cache
    to_remove = [k for k in sys.modules if k.startswith("carton")]
    for k in to_remove:
        del sys.modules[k]

    # 3. Copy files. Use a robust replace strategy: clear __pycache__
    # subdirs first (Maya's import machinery holds these open), then
    # rmtree what's left, then copytree from source. Wrapped in
    # explicit error handling so any failure is loud — silently
    # leaving the deployed dir half-deleted has caused config / profile
    # data loss reports in the past.
    if os.path.exists(_DST):
        # Drop all __pycache__/ first; these are the files Maya is
        # most likely to have open and that prevent rmtree from
        # finishing on Windows.
        for root, dirs, _files in os.walk(_DST):
            for d in list(dirs):
                if d == "__pycache__":
                    try:
                        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                    except Exception:
                        pass
        try:
            shutil.rmtree(_DST)
        except Exception as e:
            raise RuntimeError(
                "[dev_reload] Failed to remove deployed Carton at {}: {}\n"
                "Restart Maya and try again — a stale .pyc lock is the usual cause."
                .format(_DST, e)
            )
    try:
        shutil.copytree(_SRC, _DST)
    except Exception as e:
        raise RuntimeError(
            "[dev_reload] Failed to copy {} -> {}: {}\n"
            "The deployed Carton package is currently MISSING. Restart Maya"
            " and re-run dev_reload (or copy the directory manually) before"
            " using Carton again."
            .format(_SRC, _DST, e)
        )

    # 3b. Ensure the bootstrap dir is on sys.path. If the deployed
    # userSetup bootstrap is stale (or install_dir was relocated and the
    # old bootstrap added only the wrong dir to sys.path), this self-heals
    # the current session so `import carton` below still works.
    if _BOOTSTRAP_DIR not in sys.path:
        sys.path.insert(0, _BOOTSTRAP_DIR)

    # 4. Recreate menu
    import maya.cmds as cmds
    if cmds.menu("CartonMenu", exists=True):
        cmds.deleteUI("CartonMenu")
    from carton.ui.shelf import create_menu
    create_menu()

    # 5. Launch window
    import carton
    carton.show()
    print("[dev] Carton reloaded!")


reload_carton()
