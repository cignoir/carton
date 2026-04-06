"""Carton settings dialog — sidebar layout with categorized pages."""

import json
import os
import shutil

from carton.compat_urllib import urlopen, Request, URLError
from carton.ui.compat import QtWidgets, QtCore, Qt
from carton.ui.i18n import t, get_language, set_language
from carton.ui import theme


def _wide_input(parent, title, label, text="", width=480):
    """Show a wider text input dialog."""
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setFixedWidth(width)
    dialog.setStyleSheet(theme.dialog_style())
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(10)
    layout.addWidget(QtWidgets.QLabel(label))
    line = QtWidgets.QLineEdit(text)
    layout.addWidget(line)
    btn_layout = QtWidgets.QHBoxLayout()
    btn_layout.addStretch()
    ok_btn = QtWidgets.QPushButton("OK")
    ok_btn.setStyleSheet(theme.btn_primary())
    ok_btn.setDefault(True)
    ok_btn.clicked.connect(dialog.accept)
    btn_layout.addWidget(ok_btn)
    layout.addLayout(btn_layout)
    if dialog.exec_() == QtWidgets.QDialog.Accepted:
        return line.text(), True
    return "", False


class SettingsDialog(QtWidgets.QDialog):
    """Settings dialog with sidebar navigation."""

    def __init__(self, config, parent=None, self_updater=None):
        super().__init__(parent)
        self._config = config
        self._self_updater = self_updater
        self.setWindowTitle(t("settings_title"))
        self.setFixedSize(640, 500)
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

        # Language
        lang_label = QtWidgets.QLabel(t("settings_language"))
        lang_label.setStyleSheet(theme.LABEL_DIM_BOLD)
        layout.addWidget(lang_label)

        self._lang_combo = QtWidgets.QComboBox()
        self._lang_combo.setStyleSheet(theme.combobox_style())
        self._lang_combo.addItem(t("settings_language_auto"), "auto")
        self._lang_combo.addItem("English", "en")
        self._lang_combo.addItem("日本語", "ja")

        current = self._config.language
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == current:
                self._lang_combo.setCurrentIndex(i)
                break

        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        layout.addWidget(self._lang_combo)

        # Install directory
        dir_label = QtWidgets.QLabel(t("settings_install_dir"))
        dir_label.setStyleSheet(theme.LABEL_DIM_BOLD)
        layout.addWidget(dir_label)

        dir_row = QtWidgets.QHBoxLayout()
        dir_row.setSpacing(8)
        self._install_dir_edit = QtWidgets.QLineEdit(self._config.install_dir)
        self._install_dir_edit.setReadOnly(True)
        self._install_dir_edit.setStyleSheet(
            "QLineEdit {{ background: {bg}; color: {text};"
            "  border: 1px solid {border}; border-radius: 4px; padding: 4px 6px; }}".format(
                bg=theme.BG_SECONDARY, text=theme.TEXT_SECONDARY, border=theme.BORDER)
        )
        dir_row.addWidget(self._install_dir_edit, stretch=1)

        change_btn = QtWidgets.QPushButton(t("settings_install_dir_change"))
        change_btn.setStyleSheet(theme.btn_ghost_text())
        change_btn.clicked.connect(self._on_change_install_dir)
        dir_row.addWidget(change_btn)
        layout.addLayout(dir_row)

        hint = QtWidgets.QLabel(t("settings_install_dir_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "color: {}; font-size: 11px;".format(theme.TEXT_MUTED)
        )
        layout.addWidget(hint)

        # Auto-update check
        self._auto_update_checkbox = QtWidgets.QCheckBox(
            t("settings_auto_update_check")
        )
        self._auto_update_checkbox.setChecked(bool(self._config.auto_check_updates))
        self._auto_update_checkbox.toggled.connect(self._on_auto_update_toggled)
        layout.addWidget(self._auto_update_checkbox)

        auto_hint = QtWidgets.QLabel(t("settings_auto_update_hint"))
        auto_hint.setWordWrap(True)
        auto_hint.setStyleSheet(
            "color: {}; font-size: 11px;".format(theme.TEXT_MUTED)
        )
        layout.addWidget(auto_hint)

        self._check_update_btn = QtWidgets.QPushButton(t("settings_check_update_now"))
        self._check_update_btn.setStyleSheet(theme.btn_ghost_text())
        self._check_update_btn.clicked.connect(self._on_check_update_now)
        # Without a self_updater reference we can't perform the check, so
        # hide the button rather than show a dead control.
        self._check_update_btn.setVisible(self._self_updater is not None)
        layout.addWidget(self._check_update_btn, alignment=Qt.AlignLeft)

        layout.addStretch()
        return page

    def _on_auto_update_toggled(self, checked):
        self._config.auto_check_updates = bool(checked)
        self._config.save()

    def _on_check_update_now(self):
        """Manual update probe — works even when auto-check is disabled.

        Runs the GitHub probe on a background thread so the settings
        dialog stays responsive. The button is disabled for the duration
        and re-enabled when the worker finishes.
        """
        if not self._self_updater:
            return
        # Guard against double-clicks while a probe is in flight.
        if getattr(self, "_update_worker", None) and self._update_worker.isRunning():
            return

        self._check_update_btn.setEnabled(False)
        self._original_check_label = self._check_update_btn.text()
        self._check_update_btn.setText(t("checking"))

        from carton.ui.main_window import _SelfUpdateCheckWorker
        self._update_worker = _SelfUpdateCheckWorker(self._self_updater, parent=self)
        self._update_worker.finished_signal.connect(self._on_check_update_done)
        self._update_worker.start()

    def _on_check_update_done(self, result, error):
        """UI-thread slot for the manual update probe."""
        self._check_update_btn.setEnabled(True)
        if getattr(self, "_original_check_label", None):
            self._check_update_btn.setText(self._original_check_label)

        if error:
            QtWidgets.QMessageBox.warning(
                self, t("settings_auto_update_check"),
                t("settings_check_update_failed", error),
            )
            return

        if result:
            version = result[0]
            QtWidgets.QMessageBox.information(
                self, t("settings_auto_update_check"),
                t("settings_check_update_available", version),
            )
        else:
            import carton
            QtWidgets.QMessageBox.information(
                self, t("settings_auto_update_check"),
                t("settings_check_update_uptodate", carton.__version__),
            )

    def _on_change_install_dir(self):
        """Prompt for a new install_dir and migrate Carton's data there."""
        from carton.core.config import InstallDirChangeError

        current = self._config.install_dir
        # Start the picker at the parent of the current install dir so the
        # user lands somewhere sensible (their Documents folder, usually).
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

    def _on_language_changed(self, index):
        lang = self._lang_combo.itemData(index)
        self._config.language = lang
        self._config.save()
        if lang == "auto":
            from carton.ui.i18n import detect_language
            lang = detect_language()
        set_language(lang)

    # ---- Registries page ----

    def _build_registries_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        reg_label = QtWidgets.QLabel(t("settings_registries"))
        reg_label.setStyleSheet(theme.LABEL_DIM_BOLD)
        layout.addWidget(reg_label)

        self._reg_list = QtWidgets.QListWidget()
        for entry in self._config.registries:
            self._reg_list.addItem(str(entry))
        self._reg_list.itemDoubleClicked.connect(self._edit_registry)
        layout.addWidget(self._reg_list)

        reg_btn_layout = QtWidgets.QHBoxLayout()

        add_btn = QtWidgets.QPushButton(t("add"))
        add_btn.setStyleSheet(theme.btn_success())
        add_btn.clicked.connect(self._add_registry)
        reg_btn_layout.addWidget(add_btn)

        edit_btn = QtWidgets.QPushButton(t("edit"))
        edit_btn.setStyleSheet(theme.btn_ghost_text())
        edit_btn.clicked.connect(self._edit_registry)
        reg_btn_layout.addWidget(edit_btn)

        remove_btn = QtWidgets.QPushButton(t("remove"))
        remove_btn.setStyleSheet(theme.btn_danger())
        remove_btn.clicked.connect(self._remove_registry)
        reg_btn_layout.addWidget(remove_btn)

        reg_btn_layout.addStretch()

        _arrow_style = (
            "QPushButton {{ background: {bg}; color: {dim}; border: 1px solid {border};"
            "  border-radius: 4px; }}"
            "QPushButton:hover {{ color: {text}; }}"
        ).format(bg=theme.BG_SECONDARY, dim=theme.TEXT_DIM,
                 border=theme.BORDER, text=theme.TEXT_PRIMARY)

        up_btn = QtWidgets.QPushButton("▲")
        up_btn.setFixedWidth(32)
        up_btn.setStyleSheet(_arrow_style)
        up_btn.clicked.connect(self._move_up)
        reg_btn_layout.addWidget(up_btn)

        down_btn = QtWidgets.QPushButton("▼")
        down_btn.setFixedWidth(32)
        down_btn.setStyleSheet(_arrow_style)
        down_btn.clicked.connect(self._move_down)
        reg_btn_layout.addWidget(down_btn)

        layout.addLayout(reg_btn_layout)
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

    # ---- Registry operations ----

    def _add_registry(self):
        """Add a registry — local file, GitHub repo, or remote URL."""
        choices = [t("settings_add_local"), t("settings_add_github"), t("settings_add_url")]
        chosen, ok = QtWidgets.QInputDialog.getItem(
            self, t("add"), t("settings_add_method"), choices, 0, False,
        )
        if not ok:
            return

        if chosen == choices[1]:
            self._add_github_registry()
        elif chosen == choices[2]:
            self._add_remote_registry()
        else:
            self._add_local_registry()

    def _add_local_registry(self):
        """Add a local registry via file dialog."""
        path = QtWidgets.QFileDialog.getOpenFileName(
            self, t("settings_select_registry"), "",
            "Registry (registry.json);;JSON (*.json)",
        )[0]
        if not path:
            return

        base = os.path.basename(os.path.dirname(path))
        self._finish_add_registry(path, default_name=base)

    def _add_github_registry(self):
        """Add a GitHub-hosted registry. User enters owner/repo."""
        repo, ok = _wide_input(
            self, "GitHub",
            t("settings_github_placeholder"),
        )
        if not ok or not repo.strip():
            return
        repo = repo.strip().strip("/")

        # Validate format
        if "/" not in repo or repo.count("/") != 1:
            QtWidgets.QMessageBox.warning(self, "Carton", t("settings_github_invalid"))
            return

        # Resolve default branch and registry.json path via GitHub API
        try:
            api_url = "https://api.github.com/repos/{}".format(repo)
            req = Request(api_url)
            req.add_header("Accept", "application/vnd.github.v3+json")
            resp = urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            branch = data.get("default_branch", "main")
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Carton",
                t("settings_github_error", str(e)),
            )
            return

        # Try common registry.json locations
        base = "https://raw.githubusercontent.com/{}/{}".format(repo, branch)
        candidates = [
            base + "/registry/registry.json",
            base + "/registry.json",
        ]

        resolved_url = None
        for url in candidates:
            try:
                req = Request(url)
                resp = urlopen(req, timeout=10)
                if resp.getcode() == 200:
                    resolved_url = url
                    break
            except Exception:
                continue

        if not resolved_url:
            QtWidgets.QMessageBox.warning(
                self, "Carton",
                t("settings_github_no_registry", repo),
            )
            return

        # Use repo name as default registry name
        default_name = repo.split("/")[1]
        self._finish_add_registry(resolved_url, default_name=default_name)

    def _add_remote_registry(self):
        """Add a remote registry via URL input."""
        url, ok = _wide_input(
            self, t("settings_add_url"),
            t("settings_url_placeholder"),
            width=560,
        )
        if not ok or not url.strip():
            return
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            QtWidgets.QMessageBox.warning(self, "Carton", t("settings_invalid_url"))
            return

        # Guess name from URL path
        parts = url.rstrip("/").rsplit("/", 2)
        default_name = parts[-2] if len(parts) >= 2 else "remote"
        if default_name in ("raw", "main", "master"):
            default_name = parts[-3] if len(parts) >= 3 else "remote"

        self._finish_add_registry(url, default_name=default_name)

    def _finish_add_registry(self, path, default_name=""):
        """Common logic for adding a registry after path/URL is determined."""
        name, ok = _wide_input(
            self, "Registry Name",
            t("settings_registry_name"),
            text=default_name,
        )
        if not ok or not name:
            return

        for r in self._config.registries:
            if r.name == name:
                QtWidgets.QMessageBox.warning(
                    self, "Carton",
                    t("settings_already_exists", name),
                )
                return

        self._config.add_registry(name, path)
        self._config.save()
        self._reg_list.addItem(str(self._config.registries[-1]))

    def _edit_registry(self, item=None):
        """Edit the selected registry's name and path."""
        row = self._reg_list.currentRow()
        if row < 0:
            return
        entry = self._config.registries[row]

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(t("settings_edit_registry"))
        dialog.setFixedWidth(500)
        dialog.setStyleSheet(theme.dialog_style())
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        name_label = QtWidgets.QLabel(t("settings_registry_name"))
        name_label.setStyleSheet(theme.LABEL_DIM)
        layout.addWidget(name_label)
        name_input = QtWidgets.QLineEdit(entry.name)
        layout.addWidget(name_input)

        path_label = QtWidgets.QLabel(t("label_path"))
        path_label.setStyleSheet(theme.LABEL_DIM)
        layout.addWidget(path_label)
        path_input = QtWidgets.QLineEdit(entry.path)
        layout.addWidget(path_input)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QtWidgets.QPushButton(t("cancel"))
        cancel_btn.setStyleSheet(theme.btn_ghost())
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QtWidgets.QPushButton(t("save"))
        save_btn.setStyleSheet(theme.btn_primary())
        save_btn.clicked.connect(dialog.accept)
        save_btn.setDefault(True)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_name = name_input.text().strip()
            new_path = path_input.text().strip()
            if not new_name or not new_path:
                return

            from carton.core.config import RegistryEntry
            self._config.registries[row] = RegistryEntry(new_name, new_path)
            self._config.save()
            self._refresh_list()
            self._reg_list.setCurrentRow(row)

    def _remove_registry(self):
        """Remove the selected registry."""
        row = self._reg_list.currentRow()
        if row < 0:
            return
        entry = self._config.registries[row]
        reply = QtWidgets.QMessageBox.question(
            self, "Remove Registry",
            t("settings_confirm_remove", entry.name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self._config.remove_registry(entry.name)
            self._config.save()
            self._reg_list.takeItem(row)

    def _move_up(self):
        """Move the selected registry up."""
        row = self._reg_list.currentRow()
        if row <= 0:
            return
        self._config.registries[row], self._config.registries[row - 1] = \
            self._config.registries[row - 1], self._config.registries[row]
        self._config.save()
        self._refresh_list()
        self._reg_list.setCurrentRow(row - 1)

    def _move_down(self):
        """Move the selected registry down."""
        row = self._reg_list.currentRow()
        if row < 0 or row >= len(self._config.registries) - 1:
            return
        self._config.registries[row], self._config.registries[row + 1] = \
            self._config.registries[row + 1], self._config.registries[row]
        self._config.save()
        self._refresh_list()
        self._reg_list.setCurrentRow(row + 1)

    def _refresh_list(self):
        self._reg_list.clear()
        for entry in self._config.registries:
            self._reg_list.addItem(str(entry))

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
