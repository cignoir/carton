"""Carton settings dialog — registry management + uninstall."""

import json
import os
import shutil

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, Request, URLError

from carton.ui.compat import QtWidgets, QtCore, Qt
from carton.ui.i18n import t


def _wide_input(parent, title, label, text="", width=480):
    """Show a wider text input dialog."""
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setFixedWidth(width)
    dialog.setStyleSheet(
        "QDialog { background: #1e1e1e; }"
        "QLabel { color: #e0e0e0; font-size: 13px; }"
        "QLineEdit { background: #2b2b2b; border: 1px solid #3c3c3c;"
        "  border-radius: 4px; padding: 8px; color: #e0e0e0; font-size: 13px; }"
        "QLineEdit:focus { border-color: #3572A5; }"
    )
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(10)
    layout.addWidget(QtWidgets.QLabel(label))
    line = QtWidgets.QLineEdit(text)
    layout.addWidget(line)
    btn_layout = QtWidgets.QHBoxLayout()
    btn_layout.addStretch()
    ok_btn = QtWidgets.QPushButton("OK")
    ok_btn.setStyleSheet(
        "QPushButton { background: #3572A5; color: white;"
        "  border: none; border-radius: 4px; padding: 6px 20px; }"
        "QPushButton:hover { background: #4682B5; }"
    )
    ok_btn.setDefault(True)
    ok_btn.clicked.connect(dialog.accept)
    btn_layout.addWidget(ok_btn)
    layout.addLayout(btn_layout)
    if dialog.exec_() == QtWidgets.QDialog.Accepted:
        return line.text(), True
    return "", False


class SettingsDialog(QtWidgets.QDialog):
    """Add, remove, reorder registries + uninstall."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle(t("settings_title"))
        self.setFixedSize(500, 400)
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; }"
            "QLabel { color: #e0e0e0; font-size: 13px; }"
            "QListWidget {"
            "  background: #2b2b2b; border: 1px solid #3c3c3c;"
            "  border-radius: 4px; color: #e0e0e0; font-size: 13px;"
            "}"
            "QListWidget::item { padding: 6px; }"
            "QListWidget::item:selected { background: #3572A5; }"
        )
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Registry list
        reg_label = QtWidgets.QLabel(t("settings_registries"))
        reg_label.setStyleSheet("color: #888; font-size: 12px; font-weight: bold;")
        layout.addWidget(reg_label)

        self._reg_list = QtWidgets.QListWidget()
        for entry in self._config.registries:
            self._reg_list.addItem("{} — {}".format(entry.name, entry.path))
        self._reg_list.itemDoubleClicked.connect(self._edit_registry)
        layout.addWidget(self._reg_list)

        # Registry operation buttons
        reg_btn_layout = QtWidgets.QHBoxLayout()

        add_btn = QtWidgets.QPushButton(t("add"))
        add_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; border: none;"
            "  border-radius: 4px; padding: 6px 12px; }"
            "QPushButton:hover { background: #5CBF60; }"
        )
        add_btn.clicked.connect(self._add_registry)
        reg_btn_layout.addWidget(add_btn)

        edit_btn = QtWidgets.QPushButton(t("edit"))
        edit_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #e0e0e0;"
            "  border: 1px solid #3c3c3c; border-radius: 4px; padding: 6px 12px; }"
            "QPushButton:hover { background: #2b2b2b; }"
        )
        edit_btn.clicked.connect(self._edit_registry)
        reg_btn_layout.addWidget(edit_btn)

        remove_btn = QtWidgets.QPushButton(t("remove"))
        remove_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #e57373;"
            "  border: 1px solid #e57373; border-radius: 4px; padding: 6px 12px; }"
            "QPushButton:hover { background: #3c2020; }"
        )
        remove_btn.clicked.connect(self._remove_registry)
        reg_btn_layout.addWidget(remove_btn)

        reg_btn_layout.addStretch()

        up_btn = QtWidgets.QPushButton("▲")
        up_btn.setFixedWidth(32)
        up_btn.setStyleSheet(
            "QPushButton { background: #2b2b2b; color: #888; border: 1px solid #3c3c3c;"
            "  border-radius: 4px; }"
            "QPushButton:hover { color: #e0e0e0; }"
        )
        up_btn.clicked.connect(self._move_up)
        reg_btn_layout.addWidget(up_btn)

        down_btn = QtWidgets.QPushButton("▼")
        down_btn.setFixedWidth(32)
        down_btn.setStyleSheet(
            "QPushButton { background: #2b2b2b; color: #888; border: 1px solid #3c3c3c;"
            "  border-radius: 4px; }"
            "QPushButton:hover { color: #e0e0e0; }"
        )
        down_btn.clicked.connect(self._move_down)
        reg_btn_layout.addWidget(down_btn)

        layout.addLayout(reg_btn_layout)

        layout.addStretch()

        # Uninstall
        uninstall_btn = QtWidgets.QPushButton(t("settings_uninstall"))
        uninstall_btn.setStyleSheet(
            "QPushButton { color: #e57373; background: transparent;"
            "  border: 1px solid #e57373; border-radius: 4px; padding: 6px; }"
            "QPushButton:hover { background: #3c2020; }"
        )
        uninstall_btn.clicked.connect(self._uninstall_carton)
        layout.addWidget(uninstall_btn)

        # Close button
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        close_btn = QtWidgets.QPushButton(t("close"))
        close_btn.setStyleSheet(
            "QPushButton { background: #3572A5; color: white;"
            "  border: none; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #4682B5; }"
        )
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

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
        self._reg_list.addItem("{} — {}".format(name, path))

    def _edit_registry(self, item=None):
        """Edit the selected registry's name and path."""
        row = self._reg_list.currentRow()
        if row < 0:
            return
        entry = self._config.registries[row]

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(t("settings_edit_registry"))
        dialog.setFixedWidth(500)
        dialog.setStyleSheet(
            "QDialog { background: #1e1e1e; }"
            "QLabel { color: #e0e0e0; font-size: 13px; }"
            "QLineEdit { background: #2b2b2b; border: 1px solid #3c3c3c;"
            "  border-radius: 4px; padding: 8px; color: #e0e0e0; font-size: 13px; }"
            "QLineEdit:focus { border-color: #3572A5; }"
        )
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        name_label = QtWidgets.QLabel(t("settings_registry_name"))
        name_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(name_label)
        name_input = QtWidgets.QLineEdit(entry.name)
        layout.addWidget(name_input)

        path_label = QtWidgets.QLabel(t("label_path"))
        path_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(path_label)
        path_input = QtWidgets.QLineEdit(entry.path)
        layout.addWidget(path_input)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QtWidgets.QPushButton(t("cancel"))
        cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #888;"
            "  border: 1px solid #3c3c3c; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #2b2b2b; }"
        )
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QtWidgets.QPushButton(t("save"))
        save_btn.setStyleSheet(
            "QPushButton { background: #3572A5; color: white;"
            "  border: none; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #4682B5; }"
        )
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
            self._reg_list.addItem("{} — {}".format(entry.name, entry.path))

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
