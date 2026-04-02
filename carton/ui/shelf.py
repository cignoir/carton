"""Carton shelf button + menu registration."""

_SHELF_NAME = "Carton"
_MENU_NAME = "CartonMenu"
_COMMAND = "import carton; carton.show()"


def create_shelf_button():
    """Add a Carton button to the currently active shelf. Skip if it already exists."""
    import maya.cmds as cmds
    import maya.mel as mel

    top_shelf = mel.eval("$tmp = $gShelfTopLevel")
    if not cmds.shelfTabLayout(top_shelf, exists=True):
        return

    # Scan all shelf tabs to check if button already exists
    tabs = cmds.shelfTabLayout(top_shelf, q=True, childArray=True) or []
    for tab in tabs:
        buttons = cmds.shelfLayout(tab, q=True, childArray=True) or []
        for btn in buttons:
            if cmds.shelfButton(btn, q=True, exists=True):
                if cmds.shelfButton(btn, q=True, label=True) == "Carton":
                    return  # Already exists somewhere

    # Add to currently active shelf tab
    current_tab = cmds.shelfTabLayout(top_shelf, q=True, selectTab=True)
    cmds.setParent(top_shelf + "|" + current_tab)
    cmds.shelfButton(
        label="Carton",
        annotation="Open Carton Package Manager",
        command=_COMMAND,
        sourceType="python",
        image1="commandButton.png",
    )


def create_menu():
    """Create a Carton menu in the Maya main menu bar. Skip if it already exists."""
    import maya.cmds as cmds

    if cmds.menu(_MENU_NAME, exists=True):
        return

    main_window = cmds.window("MayaWindow", q=True, exists=True)
    if not main_window:
        return

    cmds.menu(
        _MENU_NAME,
        label="Carton",
        parent="MayaWindow",
        tearOff=False,
    )
    cmds.menuItem(
        label="Open Carton",
        command=_COMMAND,
        sourceType="python",
        parent=_MENU_NAME,
    )
    cmds.menuItem(divider=True, parent=_MENU_NAME)
    cmds.menuItem(
        label="Add Shelf Button",
        command="from carton.ui.shelf import create_shelf_button; create_shelf_button()",
        sourceType="python",
        parent=_MENU_NAME,
    )
    cmds.menuItem(divider=True, parent=_MENU_NAME)
    cmds.menuItem(
        label="Settings...",
        command="import carton; carton.open_settings()",
        sourceType="python",
        parent=_MENU_NAME,
    )


def setup():
    """Set up both shelf button and menu.

    Must be called after Maya UI is fully initialized,
    so it uses evalDeferred for deferred execution.
    """
    import maya.cmds as cmds
    cmds.evalDeferred(_deferred_setup, lowestPriority=True)


def _deferred_setup(*args):
    """Deferred setup. Only auto-registers the menu."""
    try:
        create_menu()
    except Exception as e:
        import traceback
        print("[Carton] Menu setup failed: {}".format(e))
        traceback.print_exc()
