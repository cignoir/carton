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

    # 1. Tear down every Qt widget that came from carton.* and the
    # surrounding workspaceControl. ``QWidget.close()`` alone is not
    # enough — MayaQWidgetDockableMixin keeps the workspaceControl
    # alive on close (so the dock slot can re-attach later), and a
    # plain ``deleteUI`` doesn't always finish the job in Maya 2027:
    # the wrapper lingers and the next ``carton.show()`` ends up with
    # two visible windows side-by-side. Three nudges in order:
    #
    #   a. Close every QWidget whose class came from carton.*
    #      (catches main window, dialogs, popup pickers, …).
    #   b. ``cmds.workspaceControl(..., e=True, close=True)`` to mark
    #      the dock closed first — required on some Maya versions
    #      before deleteUI actually destroys the C++ wrapper.
    #   c. ``cmds.deleteUI`` to remove the named control.
    #
    # Wrapped in best-effort guards so a missing optional dependency
    # (PySide, maya.cmds in unit-test contexts) doesn't abort reload.
    try:
        from carton.ui.compat import QtWidgets
    except ImportError:
        try:
            from PySide6 import QtWidgets  # type: ignore[no-redef]
        except ImportError:
            try:
                from PySide2 import QtWidgets  # type: ignore[no-redef]
            except ImportError:
                QtWidgets = None  # type: ignore[assignment]

    if QtWidgets is not None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            for w in list(app.allWidgets()):
                klass = type(w)
                mod = getattr(klass, "__module__", "") or ""
                if mod == "carton" or mod.startswith("carton."):
                    try:
                        w.close()
                        w.deleteLater()
                    except RuntimeError:
                        pass

    if "carton" in sys.modules:
        try:
            import carton
            carton._window = None
        except Exception:
            pass

    try:
        import maya.cmds as cmds
        for ctl in ("CartonWindowWorkspaceControl",):
            if cmds.workspaceControl(ctl, exists=True):
                try:
                    cmds.workspaceControl(ctl, edit=True, close=True)
                except (RuntimeError, TypeError):
                    pass
                try:
                    cmds.deleteUI(ctl)
                except RuntimeError:
                    pass
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
