"""Carton settings dialog — sidebar layout with categorized pages.

Most of the actual editor widgets live in :mod:`carton.ui.settings_widgets`
so the same code can be reused by the Profile Builder. This file holds the
shell (sidebar + stacked pages), Carton-only fields like the install_dir
mover, and the Advanced page with self-uninstall.
"""

import os
import shutil

from carton.ui.compat import QtWidgets, Qt
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.settings_widgets import (
    AutoUpdateSection,
    StrictVerifySection,
    LanguageSection,
    ProxySection,
    RegistriesSection,
)


class SettingsDialog(QtWidgets.QDialog):
    """Settings dialog with sidebar navigation."""

    def __init__(self, config, parent=None, self_updater=None):
        super().__init__(parent)
        self._config = config
        self._self_updater = self_updater
        self.setWindowTitle(t("settings_title"))
        self.setFixedSize(640, 640)
        self.setStyleSheet(
            theme.dialog_style() + theme.listwidget_style()
        )
        self._setup_ui()

    def _setup_ui(self):
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Sidebar --
        sidebar = QtWidgets.QWidget()
        sidebar.setFixedWidth(140)
        sidebar.setStyleSheet("QWidget {{ background: {}; }}".format(theme.BG_SIDEBAR))
        sb_layout = QtWidgets.QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(8, 12, 8, 12)
        sb_layout.setSpacing(4)

        self._nav = QtWidgets.QListWidget()
        self._nav.setStyleSheet(theme.sidebar_list_style())
        self._nav.addItem(t("settings_general"))
        self._nav.addItem(t("settings_registries"))
        self._nav.addItem(t("settings_advanced"))
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        sb_layout.addWidget(self._nav)
        sb_layout.addStretch()

        root.addWidget(sidebar)

        # -- Pages --
        self._pages = QtWidgets.QStackedWidget()
        self._pages.addWidget(self._build_general_page())
        self._pages.addWidget(self._build_registries_page())
        self._pages.addWidget(self._build_advanced_page())
        root.addWidget(self._pages)

        self._nav.setCurrentRow(0)

    def _on_nav_changed(self, row):
        self._pages.setCurrentIndex(row)

    # ---- General page ----

    def _build_general_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Language — uses live i18n switching since this IS the live config.
        layout.addWidget(LanguageSection(
            self._config, self._config.save, apply_live=True,
        ))

        # Install directory (Carton-specific, not part of a profile)
        self._build_install_dir_block(layout)

        # Auto-update + manual check (live mode: pass the self_updater)
        layout.addWidget(AutoUpdateSection(
            self._config, self._config.save, self_updater=self._self_updater,
        ))

        # HTTP proxy — push to env on change
        layout.addWidget(ProxySection(
            self._config, self._config.save, apply_to_env=True,
        ))

        # Strict integrity verification
        layout.addWidget(StrictVerifySection(
            self._config, self._config.save,
        ))

        # Profile Builder entry point
        builder_btn = QtWidgets.QPushButton(t("settings_open_profile_builder"))
        builder_btn.setStyleSheet(theme.btn_ghost_text())
        builder_btn.clicked.connect(self._open_profile_builder)
        layout.addWidget(builder_btn, alignment=Qt.AlignLeft)

        layout.addStretch()
        return page

    def _build_install_dir_block(self, layout):
        """Carton-only install_dir editor (not shared with the profile)."""
        dir_label = QtWidgets.QLabel(t("settings_install_dir"))
        dir_label.setStyleSheet(theme.LABEL_DIM_BOLD)
        layout.addWidget(dir_label)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self._install_dir_edit = QtWidgets.QLineEdit(self._config.install_dir)
        self._install_dir_edit.setReadOnly(True)
        self._install_dir_edit.setStyleSheet(
            "QLineEdit {{ background: {bg}; color: {text};"
            "  border: 1px solid {border}; border-radius: 4px; padding: 4px 6px; }}".format(
                bg=theme.BG_SECONDARY, text=theme.TEXT_SECONDARY, border=theme.BORDER)
        )
        row.addWidget(self._install_dir_edit, stretch=1)

        change_btn = QtWidgets.QPushButton(t("settings_install_dir_change"))
        change_btn.setStyleSheet(theme.btn_ghost_text())
        change_btn.clicked.connect(self._on_change_install_dir)
        row.addWidget(change_btn)
        layout.addLayout(row)

        hint = QtWidgets.QLabel(t("settings_install_dir_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
        layout.addWidget(hint)

    def _on_change_install_dir(self):
        """Prompt for a new install_dir and migrate Carton's data there."""
        from carton.core.config import InstallDirChangeError

        current = self._config.install_dir
        start_at = os.path.dirname(current) if os.path.isdir(current) else ""
        new_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, t("settings_install_dir_select"), start_at,
        )
        if not new_dir:
            return
        new_dir = os.path.normpath(new_dir)
        if os.path.normpath(new_dir) == os.path.normpath(current):
            return

        reply = QtWidgets.QMessageBox.question(
            self, t("settings_install_dir"),
            t("settings_install_dir_confirm", current, new_dir),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        try:
            self._config.change_install_dir(new_dir)
        except InstallDirChangeError as e:
            QtWidgets.QMessageBox.warning(
                self, t("settings_install_dir_error"), str(e),
            )
            return

        self._install_dir_edit.setText(self._config.install_dir)
        QtWidgets.QMessageBox.information(
            self, t("settings_install_dir"),
            t("settings_install_dir_restart_required", self._config.install_dir),
        )

    def _open_profile_builder(self):
        """Launch the Profile Builder dialog with the live config as a seed."""
        from carton.ui.profile_builder_dialog import ProfileBuilderDialog
        dlg = ProfileBuilderDialog(self._config, parent=self)
        dlg.exec_()

    # ---- Registries page ----

    def _build_registries_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(RegistriesSection(self._config, self._config.save))
        return page

    # ---- Advanced page ----

    def _build_advanced_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addStretch()

        uninstall_btn = QtWidgets.QPushButton(t("settings_uninstall"))
        uninstall_btn.setStyleSheet(theme.btn_danger())
        uninstall_btn.clicked.connect(self._uninstall_carton)
        layout.addWidget(uninstall_btn)

        return page

    # ---- Uninstall ----

    def _uninstall_carton(self):
        """Uninstall Carton itself."""
        reply = QtWidgets.QMessageBox.warning(
            self, t("settings_uninstall_title"),
            t("settings_confirm_uninstall"),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        errors = []

        install_dir = self._config.install_dir
        if os.path.exists(install_dir):
            try:
                shutil.rmtree(install_dir)
            except Exception as e:
                errors.append("install_dir: {}".format(e))

        try:
            import maya.cmds as cmds
            scripts_dir = cmds.internalVar(userScriptDir=True)

            bootstrap_path = os.path.join(scripts_dir, "carton_bootstrap.py")
            if os.path.exists(bootstrap_path):
                os.remove(bootstrap_path)

            usersetup_path = os.path.join(scripts_dir, "userSetup.py")
            if os.path.exists(usersetup_path):
                with open(usersetup_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if "carton_bootstrap" in content:
                    lines = content.split("\n")
                    new_lines = []
                    skip = False
                    for line in lines:
                        if "--- Carton Bootstrap ---" in line and "End" not in line:
                            skip = True
                            continue
                        if "--- End Carton Bootstrap ---" in line:
                            skip = False
                            continue
                        if not skip:
                            new_lines.append(line)
                    cleaned = "\n".join(new_lines).strip()
                    if cleaned:
                        with open(usersetup_path, "w", encoding="utf-8") as f:
                            f.write(cleaned + "\n")
                    else:
                        os.remove(usersetup_path)
        except Exception as e:
            errors.append("bootstrap cleanup: {}".format(e))

        try:
            import maya.cmds as cmds
            if cmds.menu("CartonMenu", exists=True):
                cmds.deleteUI("CartonMenu")
        except Exception:
            pass

        self.accept()

        if errors:
            QtWidgets.QMessageBox.warning(
                None, "Carton",
                t("settings_uninstall_errors", "\n".join(errors)),
            )
        else:
            QtWidgets.QMessageBox.information(
                None, "Carton",
                t("settings_uninstall_done"),
            )
