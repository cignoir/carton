"""Profile switcher flow for the main window.

Extracted from ``main_window.py``: combo rebuild, switch-on-select,
and the profile-manager dialog round trip all talk to profile_store
directly, which is domain logic the window shouldn't own. The
controller keeps a reference back to the ``CartonWindow`` — the combo
widget and ``refresh()`` remain the window's, matching the other
controllers.
"""

from carton.core.log import get_logger
from carton.ui.error_messages import show_error


class ProfileController:
    """Drives the profile combo + profile manager dialog."""

    def __init__(self, window):
        self._w = window

    def rebuild_combo(self):
        w = self._w
        if not w._config:
            return
        from carton.core import profile_store
        from carton.core.profile import InstallerProfile
        w._profile_combo.blockSignals(True)
        w._profile_combo.clear()
        names = profile_store.ordered_profiles(w._config.profile_order)
        # Recovery: if nothing is on disk (fresh install or accidental
        # state loss), materialise the default profile from the current
        # Config snapshot so the user always has at least one entry.
        if not names:
            try:
                profile_store.save_profile(
                    profile_store.DEFAULT_PROFILE_NAME,
                    InstallerProfile.from_config(w._config),
                )
                w._config.active_profile = profile_store.DEFAULT_PROFILE_NAME
                w._config.save()
                names = profile_store.ordered_profiles(w._config.profile_order)
            except Exception as e:
                get_logger().warning(
                    "could not materialise the default profile: %s", e)
        for name in names:
            w._profile_combo.addItem(name, name)
        active = w._config.active_profile or profile_store.DEFAULT_PROFILE_NAME
        idx = w._profile_combo.findData(active)
        if idx < 0:
            idx = 0
        w._profile_combo.setCurrentIndex(idx)
        w._profile_combo.blockSignals(False)

    def on_combo_changed(self, index):
        w = self._w
        if not w._config or index < 0:
            return
        new_name = w._profile_combo.itemData(index) or ""
        if new_name == w._config.active_profile:
            return
        self.switch(new_name)

    def switch(self, name):
        w = self._w
        from carton.core import profile_store
        from carton.core.profile import InvalidProfileError
        if not name:
            name = profile_store.DEFAULT_PROFILE_NAME
        try:
            profile = profile_store.load_profile(name)
        except InvalidProfileError as e:
            show_error(w, e)
            self.rebuild_combo()
            return
        w._config.apply_profile(profile)
        w._config.active_profile = name
        w._config.save()
        w._config.apply_proxy_to_env()
        w.refresh()

    def open_manager(self):
        w = self._w
        from carton.ui.profile_manager_dialog import ProfileManagerDialog
        dlg = ProfileManagerDialog(w._config, parent=w)
        dlg.exec_()
        self.rebuild_combo()
        # The user may have edited the active profile — reapply just in case.
        if w._config.active_profile:
            try:
                from carton.core import profile_store
                profile = profile_store.load_profile(w._config.active_profile)
                w._config.apply_profile(profile)
                w._config.save()
                w.refresh()
            except Exception as e:
                get_logger().warning(
                    "could not reapply profile %r after managing profiles: %s",
                    w._config.active_profile, e)
