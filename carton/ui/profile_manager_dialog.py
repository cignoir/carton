"""Profile manager — list, create, edit, delete runtime profiles.

Profiles managed here drive the active-profile dropdown in the main
window. Editing a profile uses the same section widgets as Settings and
the Profile Builder, just bound to a freshly-loaded
:class:`InstallerProfile` and persisted to ``profiles/<name>.json``
through :mod:`carton.core.profile_store` on save.
"""

import os

from carton.core import profile_store
from carton.core.profile import InstallerProfile, InvalidProfileError
from carton.ui.compat import QtWidgets, Qt
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.settings_widgets import (
    AutoUpdateSection,
    LanguageSection,
    ProxySection,
    RegistriesSection,
    wide_input,
)


class _ProfileEditDialog(QtWidgets.QDialog):
    """Edit one profile in isolation. Save writes to profiles/<name>.json."""

    def __init__(self, name, profile, parent=None):
        super().__init__(parent)
        self._name = name
        self._profile = profile
        self.setWindowTitle(t("profile_edit_title", name))
        self.setFixedSize(560, 640)
        self.setStyleSheet(theme.dialog_style() + theme.listwidget_style())

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(14)

        title = QtWidgets.QLabel(name)
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        root.addWidget(title)

        noop = lambda: None
        root.addWidget(LanguageSection(self._profile, noop, apply_live=False))
        root.addWidget(AutoUpdateSection(self._profile, noop, self_updater=None))
        root.addWidget(ProxySection(self._profile, noop, apply_to_env=False))
        root.addWidget(RegistriesSection(self._profile, noop), stretch=1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        save_btn = QtWidgets.QPushButton(t("save"))
        save_btn.setStyleSheet(theme.btn_primary())
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        cancel_btn = QtWidgets.QPushButton(t("cancel"))
        cancel_btn.setStyleSheet(theme.btn_ghost())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    def _on_save(self):
        try:
            profile_store.save_profile(self._name, self._profile)
        except (OSError, InvalidProfileError) as e:
            QtWidgets.QMessageBox.warning(self, "Carton", str(e))
            return
        self.accept()


class ProfileManagerDialog(QtWidgets.QDialog):
    """List + create + edit + delete profiles."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle(t("profile_manager_title"))
        self.setFixedSize(420, 460)
        self.setStyleSheet(theme.dialog_style() + theme.listwidget_style())

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)

        hint = QtWidgets.QLabel(t("profile_manager_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
        root.addWidget(hint)

        self._list = QtWidgets.QListWidget()
        root.addWidget(self._list, stretch=1)

        btn_row = QtWidgets.QHBoxLayout()
        new_btn = QtWidgets.QPushButton(t("profile_new"))
        new_btn.setStyleSheet(theme.btn_success())
        new_btn.clicked.connect(self._on_new)
        btn_row.addWidget(new_btn)

        edit_btn = QtWidgets.QPushButton(t("edit"))
        edit_btn.setStyleSheet(theme.btn_ghost_text())
        edit_btn.clicked.connect(self._on_edit)
        btn_row.addWidget(edit_btn)

        del_btn = QtWidgets.QPushButton(t("remove"))
        del_btn.setStyleSheet(theme.btn_danger())
        del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()

        close_btn = QtWidgets.QPushButton(t("close"))
        close_btn.setStyleSheet(theme.btn_ghost())
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._refresh()

    def _refresh(self):
        self._list.clear()
        for name in profile_store.list_profiles():
            label = name
            if name == (self._config.active_profile or ""):
                label = "{}  ({})".format(name, t("profile_active"))
            self._list.addItem(label)

    def _selected_name(self):
        row = self._list.currentRow()
        if row < 0:
            return None
        text = self._list.item(row).text()
        # Strip the active suffix if present
        return text.split("  (")[0]

    def _on_new(self):
        name, ok = wide_input(
            self, t("profile_new"), t("profile_name_prompt"),
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if not profile_store.is_valid_name(name):
            QtWidgets.QMessageBox.warning(self, "Carton", t("profile_name_invalid"))
            return
        if profile_store.profile_exists(name):
            QtWidgets.QMessageBox.warning(
                self, "Carton", t("profile_name_exists", name),
            )
            return
        # Seed from current config so the user starts with their existing
        # registries — almost always what they want.
        profile = InstallerProfile.from_config(self._config)
        try:
            profile_store.save_profile(name, profile)
        except (OSError, InvalidProfileError) as e:
            QtWidgets.QMessageBox.warning(self, "Carton", str(e))
            return
        self._refresh()

    def _on_edit(self):
        name = self._selected_name()
        if not name:
            return
        try:
            profile = profile_store.load_profile(name)
        except InvalidProfileError as e:
            QtWidgets.QMessageBox.warning(self, "Carton", str(e))
            return
        dlg = _ProfileEditDialog(name, profile, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self._refresh()

    def _on_delete(self):
        name = self._selected_name()
        if not name:
            return
        if name == (self._config.active_profile or ""):
            QtWidgets.QMessageBox.warning(
                self, "Carton", t("profile_delete_active"),
            )
            return
        reply = QtWidgets.QMessageBox.question(
            self, "Carton", t("profile_confirm_delete", name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            profile_store.delete_profile(name)
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, "Carton", str(e))
            return
        self._refresh()
