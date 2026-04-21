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
from carton.ui.error_messages import show_error
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
        self._new_name = name  # set on successful rename
        self._is_default = (name == profile_store.DEFAULT_PROFILE_NAME)
        self.setWindowTitle(t("profile_edit_title", name))
        self.setFixedSize(560, 660)
        self.setStyleSheet(theme.dialog_style() + theme.listwidget_style())

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(14)

        # Name field — disabled for the built-in default profile
        name_label = QtWidgets.QLabel(t("profile_name_prompt"))
        name_label.setStyleSheet(theme.LABEL_DIM_BOLD)
        root.addWidget(name_label)
        self._name_input = QtWidgets.QLineEdit(name)
        if self._is_default:
            self._name_input.setEnabled(False)
            self._name_input.setToolTip(
                t("profile_delete_default", profile_store.DEFAULT_PROFILE_NAME)
            )
        root.addWidget(self._name_input)

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

    def new_name(self):
        return self._new_name

    def _on_save(self):
        new_name = self._name_input.text().strip()
        if new_name != self._name:
            if not profile_store.is_valid_name(new_name):
                QtWidgets.QMessageBox.warning(
                    self, "Carton", t("profile_name_invalid"),
                )
                return
            if new_name == profile_store.DEFAULT_PROFILE_NAME:
                QtWidgets.QMessageBox.warning(
                    self, "Carton",
                    t("profile_name_reserved", profile_store.DEFAULT_PROFILE_NAME),
                )
                return
            if profile_store.profile_exists(new_name):
                QtWidgets.QMessageBox.warning(
                    self, "Carton", t("profile_name_exists", new_name),
                )
                return
        try:
            profile_store.save_profile(new_name, self._profile)
            if new_name != self._name:
                profile_store.delete_profile(self._name)
        except (OSError, InvalidProfileError) as e:
            show_error(self, e)
            return
        self._new_name = new_name
        self.accept()


class ProfileManagerDialog(QtWidgets.QDialog):
    """List + create + edit + delete profiles."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle(t("profile_manager_title"))
        self.setFixedSize(540, 480)
        self.setStyleSheet(theme.dialog_style() + theme.listwidget_style())

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)

        hint = QtWidgets.QLabel(t("profile_manager_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
        root.addWidget(hint)

        # List + reorder column to its right
        list_row = QtWidgets.QHBoxLayout()
        list_row.setSpacing(6)
        self._list = QtWidgets.QListWidget()
        list_row.addWidget(self._list, stretch=1)

        arrow_col = QtWidgets.QVBoxLayout()
        arrow_col.setSpacing(4)
        arrow_style = (
            "QPushButton {{ background: {bg}; color: {dim}; border: 1px solid {border};"
            "  border-radius: 4px; }}"
            "QPushButton:hover {{ color: {text}; }}"
        ).format(bg=theme.BG_SECONDARY, dim=theme.TEXT_DIM,
                 border=theme.BORDER, text=theme.TEXT_PRIMARY)
        up_btn = QtWidgets.QPushButton("\u25b2")
        up_btn.setFixedSize(28, 28)
        up_btn.setStyleSheet(arrow_style)
        up_btn.clicked.connect(self._on_move_up)
        arrow_col.addWidget(up_btn)
        down_btn = QtWidgets.QPushButton("\u25bc")
        down_btn.setFixedSize(28, 28)
        down_btn.setStyleSheet(arrow_style)
        down_btn.clicked.connect(self._on_move_down)
        arrow_col.addWidget(down_btn)
        arrow_col.addStretch(1)
        list_row.addLayout(arrow_col)

        root.addLayout(list_row, stretch=1)

        # Action buttons — single row, left-aligned actions + right-aligned Close
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(8)

        new_btn = QtWidgets.QPushButton(t("profile_new"))
        new_btn.setStyleSheet(theme.btn_success())
        new_btn.clicked.connect(self._on_new)
        btn_row.addWidget(new_btn)

        edit_btn = QtWidgets.QPushButton(t("edit"))
        edit_btn.setStyleSheet(theme.btn_ghost_text())
        edit_btn.clicked.connect(self._on_edit)
        btn_row.addWidget(edit_btn)

        build_btn = QtWidgets.QPushButton(t("profile_build_installer"))
        build_btn.setStyleSheet(theme.btn_ghost_text())
        build_btn.clicked.connect(self._on_build_installer)
        btn_row.addWidget(build_btn)

        del_btn = QtWidgets.QPushButton(t("remove"))
        del_btn.setStyleSheet(theme.btn_danger())
        del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(del_btn)

        btn_row.addStretch(1)

        close_btn = QtWidgets.QPushButton(t("close"))
        close_btn.setStyleSheet(theme.btn_ghost())
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._refresh()

    def _refresh(self):
        prev = self._selected_name()
        self._list.clear()
        names = profile_store.ordered_profiles(self._config.profile_order)
        # Persist any newly-discovered names so the saved order matches
        # what the user sees the next time they open the dialog.
        if names != list(self._config.profile_order or []):
            self._config.profile_order = names
            try:
                self._config.save()
            except Exception:
                pass
        for name in names:
            label = name
            if name == (self._config.active_profile or ""):
                label = "{}  ({})".format(name, t("profile_active"))
            self._list.addItem(label)
        if prev:
            for i in range(self._list.count()):
                if self._list.item(i).text().split("  (")[0] == prev:
                    self._list.setCurrentRow(i)
                    break

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
        if name == profile_store.DEFAULT_PROFILE_NAME:
            QtWidgets.QMessageBox.warning(
                self, "Carton",
                t("profile_name_reserved", profile_store.DEFAULT_PROFILE_NAME),
            )
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
            show_error(self, e)
            return
        self._refresh()

    def _on_edit(self):
        name = self._selected_name()
        if not name:
            return
        try:
            profile = profile_store.load_profile(name)
        except InvalidProfileError as e:
            show_error(self, e)
            return
        dlg = _ProfileEditDialog(name, profile, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_name = dlg.new_name()
            if new_name != name:
                # Mirror the rename into config: ordering, active flag.
                order = list(self._config.profile_order or [])
                if name in order:
                    order[order.index(name)] = new_name
                else:
                    order.append(new_name)
                self._config.profile_order = order
                if self._config.active_profile == name:
                    self._config.active_profile = new_name
                try:
                    self._config.save()
                except Exception:
                    pass
            self._refresh()

    def _on_build_installer(self):
        name = self._selected_name()
        if not name:
            return
        from carton.core.profile_store import _path_for
        profile_path = _path_for(name)
        if not os.path.exists(profile_path):
            QtWidgets.QMessageBox.warning(
                self, "Carton", t("profile_build_missing", name),
            )
            return
        default_filename = "install_carton_{}.py".format(name)
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, t("profile_build_installer"), default_filename,
            "Python (*.py)",
        )
        if not out_path:
            return
        try:
            from carton.core.installer_builder import build_from_profile
            build_from_profile(profile_path, out_path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Carton", t("profile_build_failed", str(e)),
            )
            return
        QtWidgets.QMessageBox.information(
            self, "Carton", t("profile_build_success", out_path),
        )

    def _on_move_up(self):
        self._move_selected(-1)

    def _on_move_down(self):
        self._move_selected(1)

    def _move_selected(self, delta):
        row = self._list.currentRow()
        if row < 0:
            return
        new_row = row + delta
        order = list(self._config.profile_order or [])
        if new_row < 0 or new_row >= len(order):
            return
        order[row], order[new_row] = order[new_row], order[row]
        self._config.profile_order = order
        try:
            self._config.save()
        except Exception:
            pass
        self._refresh()
        self._list.setCurrentRow(new_row)

    def _on_delete(self):
        name = self._selected_name()
        if not name:
            return
        if name == profile_store.DEFAULT_PROFILE_NAME:
            QtWidgets.QMessageBox.warning(
                self, "Carton",
                t("profile_delete_default", profile_store.DEFAULT_PROFILE_NAME),
            )
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
            show_error(self, e)
            return
        self._refresh()
