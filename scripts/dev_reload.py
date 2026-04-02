"""Carton development reload script.

Run the following in Maya's Script Editor:
    exec(open(r"F:\\workspace\\carton\\scripts\\dev_reload.py", encoding="utf-8").read())
"""

import os
import shutil
import sys

_SRC = r"F:\workspace\carton\carton"
_DST = os.path.expanduser("~/Documents/maya/carton/carton")


def reload_carton():
    # 1. Close the window
    if "carton" in sys.modules:
        import carton
        if carton._window is not None:
            try:
                carton._window.close()
            except Exception:
                pass

    # 2. Clear module cache
    to_remove = [k for k in sys.modules if k.startswith("carton")]
    for k in to_remove:
        del sys.modules[k]

    # 3. Copy files
    if os.path.exists(_DST):
        shutil.rmtree(_DST)
    shutil.copytree(_SRC, _DST)

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
