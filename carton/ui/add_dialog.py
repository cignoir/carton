"""Unified registration dialog for local scripts/packages.

Supported patterns:
  A. Single file + function call (my_tool.py -> my_tool.show())
  B. Single file + top-level execution (create_sphere.py -> exec)
  C. Folder (my_tool/ package -> import my_tool; my_tool.show())
"""

import json
import os
import re

from carton.ui.compat import QtWidgets, QtCore, Qt
from carton.ui.i18n import t


def _detect_from_folder(folder_path):
    """Auto-detect package information from a folder."""
    info = {
        "name": os.path.basename(folder_path).lower().replace("-", "_").replace(" ", "_"),
        "display_name": os.path.basename(folder_path),
        "type": "python_package",
        "function": "show",
        "is_folder": True,
    }

    # Read from package.json if it exists
    pkg_json = os.path.join(folder_path, "package.json")
    if os.path.exists(pkg_json):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            info["name"] = data.get("name", info["name"])
            info["display_name"] = data.get("display_name", info["display_name"])
            info["type"] = data.get("type", info["type"])
            ep = data.get("entry_point", {})
            if isinstance(ep, dict):
                info["function"] = ep.get("function", ep.get("procedure", "show"))
            if data.get("id"):
                info["id"] = data["id"]
            info["icon"] = data.get("icon", "")
            info["description"] = data.get("description", "")
            info["version"] = data.get("version", "0.0.0")
            info["author"] = data.get("author", "")
            info["has_package_json"] = True
            info["entry_point"] = data.get("entry_point", {})
            return info
        except (json.JSONDecodeError, OSError):
            pass

    # Detect functions from __init__.py
    init_py = os.path.join(folder_path, info["name"], "__init__.py")
    if not os.path.exists(init_py):
        # May be directly in the folder
        init_py = os.path.join(folder_path, "__init__.py")
    if os.path.exists(init_py):
        info["function"] = _detect_function_in_file(init_py) or "show"

    # Detect MEL / Plugin
    extensions = set()
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            extensions.add(os.path.splitext(f)[1].lower())
    if ".mll" in extensions:
        info["type"] = "plugin"
    elif ".mel" in extensions and ".py" not in extensions:
        info["type"] = "mel_script"

    return info


def _detect_function_in_file(path):
    """Detect a callable function from a Python file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        for name in ["show", "run", "main", "execute"]:
            if re.search(r"^def {}\s*\(".format(name), content, re.MULTILINE):
                return name

        match = re.search(r"^def ([a-zA-Z][a-zA-Z0-9_]*)\s*\(", content, re.MULTILINE)
        if match:
            return match.group(1)
    except (OSError, UnicodeDecodeError):
        pass
    return None


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


def _has_functions(path):
    """Check whether the file contains def statements."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("def "):
                    return True
    except (OSError, UnicodeDecodeError):
        pass
    return False


class AddDialog(QtWidgets.QDialog):
    """Unified dialog for locally registering files/folders."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("add_title"))
        self.setFixedSize(440, 360)
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; }"
            "QLabel { color: #e0e0e0; font-size: 13px; }"
            "QLineEdit {"
            "  background: #2b2b2b; border: 1px solid #3c3c3c;"
            "  border-radius: 4px; padding: 6px; color: #e0e0e0;"
            "  font-size: 13px;"
            "}"
            "QLineEdit:focus { border-color: #3572A5; }"
            "QRadioButton { color: #e0e0e0; font-size: 13px; }"
        )

        self._result = None
        self._selected_path = ""
        self._is_folder = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        # File / folder selection
        select_layout = QtWidgets.QHBoxLayout()
        self._path_input = QtWidgets.QLineEdit()
        self._path_input.setPlaceholderText(t("add_select_placeholder"))
        self._path_input.setReadOnly(True)
        select_layout.addWidget(self._path_input)

        file_btn = QtWidgets.QPushButton(t("file"))
        file_btn.setStyleSheet(
            "QPushButton { background: #3c3c3c; color: #e0e0e0; border: none;"
            "  border-radius: 4px; padding: 6px 10px; }"
            "QPushButton:hover { background: #4c4c4c; }"
        )
        file_btn.clicked.connect(self._browse_file)
        select_layout.addWidget(file_btn)

        folder_btn = QtWidgets.QPushButton(t("folder"))
        folder_btn.setStyleSheet(
            "QPushButton { background: #3c3c3c; color: #e0e0e0; border: none;"
            "  border-radius: 4px; padding: 6px 10px; }"
            "QPushButton:hover { background: #4c4c4c; }"
        )
        folder_btn.clicked.connect(self._browse_folder)
        select_layout.addWidget(folder_btn)
        layout.addLayout(select_layout)

        # Form
        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        label_style = "color: #888; font-size: 12px;"

        name_label = QtWidgets.QLabel(t("label_display_name"))
        name_label.setStyleSheet(label_style)
        self._name_input = QtWidgets.QLineEdit()
        form.addRow(name_label, self._name_input)

        icon_label = QtWidgets.QLabel(t("label_icon"))
        icon_label.setStyleSheet(label_style)
        icon_row = QtWidgets.QHBoxLayout()
        self._icon_input = QtWidgets.QLineEdit("🔧")
        icon_row.addWidget(self._icon_input)
        icon_browse_btn = QtWidgets.QPushButton(t("file"))
        icon_browse_btn.setFixedWidth(60)
        icon_browse_btn.setStyleSheet(
            "QPushButton { background: #2b2b2b; color: #aaa;"
            "  border: 1px solid #3c3c3c; border-radius: 4px; padding: 4px; font-size: 12px; }"
            "QPushButton:hover { background: #3a3a3a; }"
        )
        icon_browse_btn.clicked.connect(self._browse_icon)
        icon_row.addWidget(icon_browse_btn)
        form.addRow(icon_label, icon_row)

        desc_label = QtWidgets.QLabel(t("label_description"))
        desc_label.setStyleSheet(label_style)
        self._desc_input = QtWidgets.QLineEdit()
        form.addRow(desc_label, self._desc_input)

        layout.addLayout(form)

        # Run mode
        self._mode_group = QtWidgets.QGroupBox(t("label_run_mode"))
        mode_group = self._mode_group
        mode_group.setStyleSheet(
            "QGroupBox { color: #888; font-size: 12px; border: 1px solid #3c3c3c;"
            "  border-radius: 4px; margin-top: 8px; padding-top: 16px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; }"
        )
        mode_layout = QtWidgets.QVBoxLayout(mode_group)

        self._mode_exec = QtWidgets.QRadioButton(t("add_exec_mode"))
        self._mode_exec.setChecked(True)
        mode_layout.addWidget(self._mode_exec)

        self._mode_func = QtWidgets.QRadioButton(t("add_func_mode"))
        mode_func_layout = QtWidgets.QHBoxLayout()
        mode_func_layout.addWidget(self._mode_func)
        self._func_combo = QtWidgets.QComboBox()
        self._func_combo.setEditable(True)
        self._func_combo.setStyleSheet(
            "QComboBox { background: #2b2b2b; border: 1px solid #3c3c3c;"
            "  border-radius: 4px; padding: 4px 6px; color: #e0e0e0; font-size: 13px; }"
            "QComboBox:focus { border-color: #3572A5; }"
            "QComboBox QAbstractItemView { background: #2b2b2b; color: #e0e0e0;"
            "  selection-background-color: #3572A5; }"
        )
        self._func_combo.lineEdit().setPlaceholderText(t("label_function"))
        mode_func_layout.addWidget(self._func_combo)
        mode_layout.addLayout(mode_func_layout)

        layout.addWidget(mode_group)

        layout.addStretch()

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QtWidgets.QPushButton(t("cancel"))
        cancel_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #888;"
            "  border: 1px solid #3c3c3c; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #2b2b2b; }"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        register_btn = QtWidgets.QPushButton(t("register"))
        register_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white;"
            "  border: none; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background: #5CBF60; }"
        )
        register_btn.clicked.connect(self._on_register)
        register_btn.setDefault(True)
        btn_layout.addWidget(register_btn)

        layout.addLayout(btn_layout)

    def _browse_icon(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, t("label_icon"), "",
            "Images (*.png *.jpg *.svg);;All (*)",
        )
        if path:
            self._icon_input.setText(path)

    def _browse_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, t("add_browse_file"), "",
            "Scripts (*.py *.mel);;Python (*.py);;MEL (*.mel)",
        )
        if not path:
            return
        self._set_path(path, is_folder=False)

    def _browse_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, t("add_browse_folder"))
        if not path:
            return
        self._set_path(path, is_folder=True)

    def _set_path(self, path, is_folder):
        self._selected_path = path
        self._is_folder = is_folder
        self._path_input.setText(path)

        if is_folder:
            info = _detect_from_folder(path)
            self._detected_info = info
            self._name_input.setText(info.get("display_name", ""))
            self._func_combo.clear()
            self._func_combo.addItem(info.get("function", "show"))
            self._func_combo.setCurrentIndex(0)
            if info.get("icon"):
                self._icon_input.setText(info["icon"])
            if info.get("description"):
                self._desc_input.setText(info["description"])

            if info.get("has_package_json"):
                # package.json exists: hide Run mode (auto-resolved)
                self._mode_group.setVisible(False)
            else:
                # No package.json: show Run mode, function call only
                self._mode_group.setVisible(True)
                self._mode_func.setChecked(True)
                self._mode_exec.setEnabled(False)
        else:
            self._detected_info = None
            self._mode_group.setVisible(True)
            self._mode_exec.setEnabled(True)
            basename = os.path.splitext(os.path.basename(path))[0]
            display = basename.replace("_", " ").replace("-", " ").title()
            self._name_input.setText(display)
            self._mode_exec.setChecked(True)

            # Populate function list in dropdown
            self._func_combo.clear()
            if path.endswith(".py"):
                funcs = _list_functions(path)
                if funcs:
                    self._func_combo.addItems(funcs)
                    self._func_combo.setCurrentIndex(0)
            elif path.endswith(".mel"):
                self._func_combo.addItem(basename)
                self._func_combo.setCurrentIndex(0)

    def _on_register(self):
        path = self._selected_path
        display_name = self._name_input.text().strip()

        if not path or (not os.path.isfile(path) and not os.path.isdir(path)):
            QtWidgets.QMessageBox.warning(self, "Carton", t("add_invalid_path"))
            return
        if not display_name:
            QtWidgets.QMessageBox.warning(self, "Carton", t("add_no_display_name"))
            return

        is_exec_mode = self._mode_exec.isChecked()
        func = self._func_combo.currentText().strip()
        icon = self._icon_input.text().strip() or "🔧"
        description = self._desc_input.text().strip()

        if self._is_folder:
            # If package.json exists, use its entry_point directly
            info = getattr(self, "_detected_info", None)
            if info and info.get("has_package_json"):
                result = {
                    "file_path": path,
                    "name": info.get("name", ""),
                    "display_name": display_name,
                    "version": info.get("version", "0.0.0"),
                    "author": info.get("author", ""),
                    "icon": icon,
                    "description": description,
                    "type": info.get("type", "python_package"),
                    "entry_point": info.get("entry_point", {}),
                    "is_folder": True,
                }
                if info.get("id"):
                    result["id"] = info["id"]
                self._result = result
                self.accept()
                return
            self._result = self._build_folder_result(path, display_name, func, icon, description)
        else:
            self._result = self._build_file_result(path, display_name, func, icon, description, is_exec_mode)

        self.accept()

    def _build_file_result(self, path, display_name, func, icon, description, is_exec_mode):
        basename = os.path.splitext(os.path.basename(path))[0]
        is_mel = path.endswith(".mel")

        if is_exec_mode:
            entry_point = {
                "type": "exec",
                "file": os.path.basename(path),
            }
            pkg_type = "mel_script" if is_mel else "python_package"
        elif is_mel:
            entry_point = {
                "type": "mel",
                "script": os.path.basename(path),
                "procedure": func or basename,
            }
            pkg_type = "mel_script"
        else:
            entry_point = {
                "type": "python",
                "module": basename,
                "function": func or "show",
            }
            pkg_type = "python_package"

        return {
            "file_path": path,
            "name": basename,
            "display_name": display_name,
            "icon": icon,
            "description": description,
            "type": pkg_type,
            "entry_point": entry_point,
            "is_folder": False,
        }

    def _build_folder_result(self, path, display_name, func, icon, description):
        info = _detect_from_folder(path)
        name = info["name"]
        pkg_type = info["type"]

        if pkg_type == "mel_script":
            # MEL folder: find the first .mel in scripts/
            mel_files = []
            scripts_dir = os.path.join(path, "scripts")
            search_dir = scripts_dir if os.path.isdir(scripts_dir) else path
            for f in os.listdir(search_dir):
                if f.endswith(".mel"):
                    mel_files.append(f)
            script_file = mel_files[0] if mel_files else "{}.mel".format(name)
            entry_point = {
                "type": "mel",
                "script": script_file,
                "procedure": func or os.path.splitext(script_file)[0],
            }
        else:
            entry_point = {
                "type": "python",
                "module": name,
                "function": func or "show",
            }

        return {
            "file_path": path,
            "name": name,
            "display_name": display_name,
            "icon": icon,
            "description": description,
            "type": pkg_type,
            "entry_point": entry_point,
            "is_folder": True,
        }

    def get_result(self):
        return self._result

    @classmethod
    def prompt(cls, parent=None):
        dialog = cls(parent)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            return dialog.get_result()
        return None
