"""Carton settings dialog — registry management + uninstall."""

import os
import shutil

from carton.ui.compat import QtWidgets, QtCore, Qt


class SettingsDialog(QtWidgets.QDialog):
    """Add, remove, reorder registries + uninstall."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Carton — Settings")
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
        reg_label = QtWidgets.QLabel("Registries")
        reg_label.setStyleSheet("color: #888; font-size: 12px; font-weight: bold;")
        layout.addWidget(reg_label)

        self._reg_list = QtWidgets.QListWidget()
        for entry in self._config.registries:
            self._reg_list.addItem("{} — {}".format(entry.name, entry.path))
        layout.addWidget(self._reg_list)

        # Registry operation buttons
        reg_btn_layout = QtWidgets.QHBoxLayout()

        add_btn = QtWidgets.QPushButton("+ Add")
        add_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; border: none;"
            "  border-radius: 4px; padding: 6px 12px; }"
            "QPushButton:hover { background: #5CBF60; }"
        )
        add_btn.clicked.connect(self._add_registry)
        reg_btn_layout.addWidget(add_btn)

        remove_btn = QtWidgets.QPushButton("Remove")
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
        uninstall_btn = QtWidgets.QPushButton("Carton をアンインストール")
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

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.setStyleSheet(
            "QPushButton { background: #3572A5; color: white;"
            "  border: none; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #4682B5; }"
        )
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _add_registry(self):
        """Add a registry."""
        path = QtWidgets.QFileDialog.getOpenFileName(
            self, "registry.json を選択", "",
            "Registry (registry.json);;JSON (*.json)",
        )[0]
        if not path:
            return

        # Guess name from folder name
        base = os.path.basename(os.path.dirname(path))
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Registry Name",
            "レジストリの名前を入力:",
            text=base,
        )
        if not ok or not name:
            return

        # Duplicate check
        for r in self._config.registries:
            if r.name == name:
                QtWidgets.QMessageBox.warning(
                    self, "Carton",
                    "'{}' は既に登録されています。".format(name),
                )
                return

        self._config.add_registry(name, path)
        self._config.save()
        self._reg_list.addItem("{} — {}".format(name, path))

    def _remove_registry(self):
        """Remove the selected registry."""
        row = self._reg_list.currentRow()
        if row < 0:
            return
        entry = self._config.registries[row]
        reply = QtWidgets.QMessageBox.question(
            self, "Remove Registry",
            "'{}' を削除しますか？\nレジストリの中身は削除されません。".format(entry.name),
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
            self, "Carton アンインストール",
            "Carton とインストール済みの全パッケージを削除します。\n"
            "この操作は取り消せません。\n\n続行しますか？",
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
                "一部エラーが発生しました:\n" + "\n".join(errors)
                + "\n\nMaya を再起動してください。",
            )
        else:
            QtWidgets.QMessageBox.information(
                None, "Carton",
                "Carton をアンインストールしました。\n"
                "Maya を再起動してください。",
            )
