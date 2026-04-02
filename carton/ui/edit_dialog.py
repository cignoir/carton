"""Dialog for editing metadata of local tools."""

import os
import re

from carton.ui.compat import QtWidgets, QtCore, Qt


def _list_functions(path):
    """Return a list of all public function names in a Python file."""
    functions = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^def ([a-zA-Z][a-zA-Z0-9_]*)\s*\(", line)
                if m:
                    functions.append(m.group(1))
    except (OSError, UnicodeDecodeError):
        pass
    return functions


class EditDialog(QtWidgets.QDialog):
    """Dialog for editing metadata of locally registered tools."""

    def __init__(self, pkg_id, pkg_data, parent=None):
        super().__init__(parent)
        self._pkg_id = pkg_id
        self._pkg_data = pkg_data
        self._result = None

        self.setWindowTitle("Carton — Edit")
        self.setFixedSize(440, 380)
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; }"
            "QLabel { color: #e0e0e0; font-size: 13px; }"
            "QLineEdit, QComboBox {"
            "  background: #2b2b2b; border: 1px solid #3c3c3c;"
            "  border-radius: 4px; padding: 6px; color: #e0e0e0;"
            "  font-size: 13px;"
            "}"
            "QLineEdit:focus, QComboBox:focus { border-color: #3572A5; }"
            "QRadioButton { color: #e0e0e0; font-size: 13px; }"
            "QComboBox QAbstractItemView { background: #2b2b2b; color: #e0e0e0;"
            "  selection-background-color: #3572A5; }"
        )

        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        label_style = "color: #888; font-size: 12px;"

        # Display Name
        name_label = QtWidgets.QLabel("Display Name")
        name_label.setStyleSheet(label_style)
        self._name_input = QtWidgets.QLineEdit(self._pkg_data.get("display_name", ""))
        form.addRow(name_label, self._name_input)

        # Version
        ver_label = QtWidgets.QLabel("Version")
        ver_label.setStyleSheet(label_style)
        self._ver_input = QtWidgets.QLineEdit(self._pkg_data.get("version", "0.0.0"))
        form.addRow(ver_label, self._ver_input)

        # Icon
        icon_label = QtWidgets.QLabel("Icon")
        icon_label.setStyleSheet(label_style)
        self._icon_input = QtWidgets.QLineEdit(self._pkg_data.get("icon", "🔧"))
        self._icon_input.setMaximumWidth(60)
        form.addRow(icon_label, self._icon_input)

        # Description
        desc_label = QtWidgets.QLabel("Description")
        desc_label.setStyleSheet(label_style)
        self._desc_input = QtWidgets.QLineEdit(self._pkg_data.get("description", ""))
        form.addRow(desc_label, self._desc_input)

        # Local Path (read-only)
        local_path = self._pkg_data.get("local_path", "")
        if local_path:
            path_label = QtWidgets.QLabel("Path")
            path_label.setStyleSheet(label_style)
            path_val = QtWidgets.QLineEdit(local_path)
            path_val.setReadOnly(True)
            path_val.setStyleSheet(path_val.styleSheet() + " color: #666;")
            form.addRow(path_label, path_val)

        layout.addLayout(form)

        # Run Mode
        entry = self._pkg_data.get("entry_point", {})
        ep_type = entry.get("type", "python")

        mode_group = QtWidgets.QGroupBox("Run Mode")
        mode_group.setStyleSheet(
            "QGroupBox { color: #888; font-size: 12px; border: 1px solid #3c3c3c;"
            "  border-radius: 4px; margin-top: 8px; padding-top: 16px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        mode_layout = QtWidgets.QVBoxLayout(mode_group)

        self._mode_exec = QtWidgets.QRadioButton("Execute file (トップレベル実行)")
        mode_layout.addWidget(self._mode_exec)

        self._mode_func = QtWidgets.QRadioButton("Call function:")
        mode_func_layout = QtWidgets.QHBoxLayout()
        mode_func_layout.addWidget(self._mode_func)
        self._func_combo = QtWidgets.QComboBox()
        self._func_combo.setEditable(True)
        mode_func_layout.addWidget(self._func_combo)
        mode_layout.addLayout(mode_func_layout)

        # Populate function list in dropdown
        if local_path and os.path.isfile(local_path) and local_path.endswith(".py"):
            funcs = _list_functions(local_path)
            if funcs:
                self._func_combo.addItems(funcs)
                self._func_combo.setCurrentIndex(0)

        # Configure based on current entry_point
        if ep_type == "exec":
            self._mode_exec.setChecked(True)
        else:
            self._mode_func.setChecked(True)
            func_name = entry.get("function", entry.get("procedure", ""))
            if func_name:
                idx = self._func_combo.findText(func_name)
                if idx >= 0:
                    self._func_combo.setCurrentIndex(idx)
                else:
                    self._func_combo.setEditText(func_name)

        # Disable exec mode for folders
        if self._pkg_data.get("is_folder"):
            self._mode_exec.setEnabled(False)
            self._mode_func.setChecked(True)

        layout.addWidget(mode_group)
        layout.addStretch()

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()

        # Remove button (left-aligned)
        remove_btn = QtWidgets.QPushButton("Remove")
        remove_btn.setStyleSheet(
            "QPushButton { color: #e57373; background: transparent;"
            "  border: 1px solid #e57373; border-radius: 4px; padding: 6px 12px; }"
            "QPushButton:hover { background: #3c2020; }"
        )
        remove_btn.clicked.connect(self._on_remove)
        btn_layout.addWidget(remove_btn)

        btn_layout.addStretch()

        cancel_btn = QtWidgets.QPushButton("キャンセル")
        cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #888;"
            "  border: 1px solid #3c3c3c; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #2b2b2b; }"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QtWidgets.QPushButton("Save")
        save_btn.setStyleSheet(
            "QPushButton { background: #3572A5; color: white;"
            "  border: none; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #4682B5; }"
        )
        save_btn.clicked.connect(self._on_save)
        save_btn.setDefault(True)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _on_save(self):
        display_name = self._name_input.text().strip()
        if not display_name:
            QtWidgets.QMessageBox.warning(self, "Carton", "Display Name を入力してください。")
            return

        name = self._pkg_data.get("name", "")
        is_mel = self._pkg_data.get("local_path", "").endswith(".mel")

        if self._mode_exec.isChecked():
            entry_point = {
                "type": "exec",
                "file": os.path.basename(self._pkg_data.get("local_path", "")),
            }
        elif is_mel:
            entry_point = {
                "type": "mel",
                "script": os.path.basename(self._pkg_data.get("local_path", "")),
                "procedure": self._func_combo.currentText().strip() or name,
            }
        else:
            entry_point = {
                "type": "python",
                "module": name,
                "function": self._func_combo.currentText().strip() or "show",
            }

        self._result = {
            "action": "save",
            "display_name": display_name,
            "version": self._ver_input.text().strip() or "0.0.0",
            "icon": self._icon_input.text().strip() or "🔧",
            "description": self._desc_input.text().strip(),
            "entry_point": entry_point,
        }
        self.accept()

    def _on_remove(self):
        display = self._pkg_data.get("display_name", self._pkg_id)
        reply = QtWidgets.QMessageBox.question(
            self, "Remove",
            "{} の登録を解除しますか？\n元ファイルは削除されません。".format(display),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self._result = {"action": "remove"}
            self.accept()

    def get_result(self):
        return self._result

    @classmethod
    def prompt(cls, pkg_id, pkg_data, parent=None):
        dialog = cls(pkg_id, pkg_data, parent)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            return dialog.get_result()
        return None
