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
from carton.ui import theme
from carton.ui.utils import list_functions
from carton.core.sidecar import read_sidecar
from carton.core.identity import (
    slugify_namespace, slugify_name, is_valid_python_module_name,
)
from carton.core.maya_module_detect import detect as detect_maya_module


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
            if data.get("namespace"):
                info["namespace"] = data["namespace"]
            if data.get("home_registry"):
                info["home_registry"] = data["home_registry"]
            info["icon"] = data.get("icon", "")
            info["description"] = data.get("description", "")
            info["version"] = data.get("version", "0.0.0")
            info["author"] = data.get("author", "")
            info["has_package_json"] = True
            info["entry_point"] = data.get("entry_point", {})
            return info
        except (json.JSONDecodeError, OSError):
            pass

    # Detect Maya module (Application Package or .mod) before falling back
    # to the extension scan. Carton package.json above already short-circuited.
    mod_info = detect_maya_module(folder_path)
    if mod_info.get("is_module"):
        info["type"] = "maya_module"
        info["is_maya_module"] = True
        info["name"] = mod_info.get("name") or info["name"]
        info["display_name"] = mod_info.get("name") or info["display_name"]
        info["entry_point"] = {}
        return info

    # Detect functions from __init__.py
    init_py = os.path.join(folder_path, info["name"], "__init__.py")
    if not os.path.exists(init_py):
        # May be directly in the folder
        init_py = os.path.join(folder_path, "__init__.py")
    if os.path.exists(init_py):
        info["function"] = _detect_function_in_file(init_py) or "show"

    # Detect MEL / Plugin via priority: any Python source in the tree
    # wins (because Python tooling may legitimately ship .mll helpers
    # alongside it — e.g. an in-house scripts/ folder containing both
    # animation tools and a vendored exAttrEditor.mll). Only fall back
    # to plugin / mel_script when there is no Python at all.
    extensions = set()
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            extensions.add(os.path.splitext(f)[1].lower())
    has_py = ".py" in extensions
    has_pyc = ".pyc" in extensions
    if has_py or has_pyc:
        info["type"] = "python_package"
    elif ".mll" in extensions:
        info["type"] = "plugin"
    elif ".mel" in extensions:
        info["type"] = "mel_script"

    # Auto-include .pyc when there is no .py source to ship — that's the
    # only situation where stripping compiled bytecode would lose data.
    info["include_compiled"] = has_pyc and not has_py

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
        self.setFixedSize(440, 440)
        self.setStyleSheet(
            theme.dialog_style(
                "QRadioButton {{ color: {text}; font-size: 13px; }}".format(
                    text=theme.TEXT_PRIMARY)
            )
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
        file_btn.setStyleSheet(theme.btn_muted())
        file_btn.clicked.connect(self._browse_file)
        select_layout.addWidget(file_btn)

        folder_btn = QtWidgets.QPushButton(t("folder"))
        folder_btn.setStyleSheet(theme.btn_muted())
        folder_btn.clicked.connect(self._browse_folder)
        select_layout.addWidget(folder_btn)
        layout.addLayout(select_layout)

        # Form
        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        name_label = QtWidgets.QLabel(t("label_display_name"))
        name_label.setStyleSheet(theme.LABEL_DIM)
        self._name_input = QtWidgets.QLineEdit()
        form.addRow(name_label, self._name_input)

        slug_label = QtWidgets.QLabel(t("label_name"))
        slug_label.setStyleSheet(theme.LABEL_DIM)
        self._slug_display = QtWidgets.QLineEdit()
        self._slug_display.setReadOnly(True)
        self._slug_display.setPlaceholderText("(select a file or folder)")
        self._slug_display.setToolTip(t("name_tooltip"))
        slug_label.setToolTip(t("name_tooltip"))
        self._slug_display.setStyleSheet(
            self._slug_display.styleSheet() + " color: {};".format(theme.TEXT_DIM)
        )
        form.addRow(slug_label, self._slug_display)

        ns_label = QtWidgets.QLabel(t("label_namespace"))
        ns_label.setStyleSheet(theme.LABEL_DIM)
        self._namespace_input = QtWidgets.QLineEdit()
        self._namespace_input.setPlaceholderText(t("namespace_placeholder"))
        self._namespace_input.textChanged.connect(self._update_namespace_preview)
        form.addRow(ns_label, self._namespace_input)
        # Slug preview lives on its own row so the input doesn't get squished
        # when the wrapper widget tries to share vertical space.
        self._namespace_preview = QtWidgets.QLabel("")
        self._namespace_preview.setStyleSheet(
            "color: {}; font-size: 11px;".format(theme.TEXT_MUTED)
        )
        self._namespace_preview.setVisible(False)
        form.addRow("", self._namespace_preview)

        icon_label = QtWidgets.QLabel(t("label_icon"))
        icon_label.setStyleSheet(theme.LABEL_DIM)
        icon_row = QtWidgets.QHBoxLayout()
        self._icon_input = QtWidgets.QLineEdit("🔧")
        icon_row.addWidget(self._icon_input)
        icon_browse_btn = QtWidgets.QPushButton(t("file"))
        icon_browse_btn.setFixedWidth(60)
        icon_browse_btn.setStyleSheet(theme.btn_small_browse())
        icon_browse_btn.clicked.connect(self._browse_icon)
        icon_row.addWidget(icon_browse_btn)
        form.addRow(icon_label, icon_row)

        desc_label = QtWidgets.QLabel(t("label_description"))
        desc_label.setStyleSheet(theme.LABEL_DIM)
        self._desc_input = QtWidgets.QLineEdit()
        form.addRow(desc_label, self._desc_input)

        layout.addLayout(form)

        # Run mode
        self._mode_group = QtWidgets.QGroupBox(t("label_run_mode"))
        mode_group = self._mode_group
        mode_group.setStyleSheet(theme.groupbox_style())
        mode_layout = QtWidgets.QVBoxLayout(mode_group)

        self._mode_exec = QtWidgets.QRadioButton(t("add_exec_mode"))
        self._mode_exec.setChecked(True)
        mode_layout.addWidget(self._mode_exec)

        self._mode_func = QtWidgets.QRadioButton(t("add_func_mode"))
        mode_func_layout = QtWidgets.QHBoxLayout()
        mode_func_layout.addWidget(self._mode_func)
        self._func_combo = QtWidgets.QComboBox()
        self._func_combo.setEditable(True)
        self._func_combo.setStyleSheet(theme.combobox_style())
        self._func_combo.lineEdit().setPlaceholderText(t("label_function"))
        mode_func_layout.addWidget(self._func_combo)
        mode_layout.addLayout(mode_func_layout)

        layout.addWidget(mode_group)

        # Plugin command (only shown for .mll files)
        self._plugin_cmd_label = QtWidgets.QLabel(t("label_plugin_command"))
        self._plugin_cmd_label.setStyleSheet(theme.LABEL_DIM)
        self._plugin_cmd_input = QtWidgets.QLineEdit()
        self._plugin_cmd_input.setPlaceholderText(
            "import maya.cmds as mc; mc.exAttrEditor(ui=True)"
        )
        self._plugin_cmd_label.setVisible(False)
        self._plugin_cmd_input.setVisible(False)
        layout.addWidget(self._plugin_cmd_label)
        layout.addWidget(self._plugin_cmd_input)

        layout.addStretch()

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QtWidgets.QPushButton(t("cancel"))
        cancel_btn.setStyleSheet(theme.btn_ghost())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        register_btn = QtWidgets.QPushButton(t("register"))
        register_btn.setStyleSheet(theme.btn_success())
        register_btn.clicked.connect(self._on_register)
        register_btn.setDefault(True)
        btn_layout.addWidget(register_btn)

        layout.addLayout(btn_layout)

    def _update_namespace_preview(self, text):
        slug = slugify_namespace(text)
        if slug and slug != text.strip().lower():
            self._namespace_preview.setText("→ {}".format(slug))
            self._namespace_preview.setVisible(True)
        else:
            self._namespace_preview.setText("")
            self._namespace_preview.setVisible(False)

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
            "Scripts (*.py *.pyc *.mel *.mll);;Python (*.py *.pyc);;MEL (*.mel);;Plugin (*.mll)",
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

        # Hide plugin command by default; only shown for .mll files
        self._plugin_cmd_label.setVisible(False)
        self._plugin_cmd_input.setVisible(False)

        if is_folder:
            info = _detect_from_folder(path)
            self._detected_info = info
            self._name_input.setText(info.get("display_name", ""))
            self._slug_display.setText(slugify_name(info.get("name", "")))
            if info.get("namespace"):
                self._namespace_input.setText(info["namespace"])
            self._func_combo.clear()
            self._func_combo.addItem(info.get("function", "show"))
            self._func_combo.setCurrentIndex(0)
            if info.get("icon"):
                self._icon_input.setText(info["icon"])
            if info.get("description"):
                self._desc_input.setText(info["description"])

            if info.get("has_package_json") or info.get("is_maya_module"):
                # package.json or Maya module: hide Run mode (auto-resolved)
                self._mode_group.setVisible(False)
            else:
                # No package.json: show Run mode, function call only
                self._mode_group.setVisible(True)
                self._mode_func.setChecked(True)
                self._mode_exec.setEnabled(False)
        else:
            # Single file: prefill from sidecar if present
            sidecar = read_sidecar(path)
            self._detected_info = {"sidecar": sidecar} if sidecar else None
            is_pyc = path.endswith(".pyc")
            self._mode_group.setVisible(True)
            self._mode_exec.setEnabled(not is_pyc)
            if is_pyc:
                self._mode_func.setChecked(True)
            basename = os.path.splitext(os.path.basename(path))[0]
            display = basename.replace("_", " ").replace("-", " ").title()
            self._slug_display.setText(slugify_name(basename))
            if sidecar:
                self._name_input.setText(sidecar.get("display_name", display))
                if sidecar.get("namespace"):
                    self._namespace_input.setText(sidecar["namespace"])
                if sidecar.get("icon"):
                    self._icon_input.setText(sidecar["icon"])
                if sidecar.get("description"):
                    self._desc_input.setText(sidecar["description"])
            else:
                self._name_input.setText(display)
            self._mode_exec.setChecked(True)

            # Populate function list in dropdown
            self._func_combo.clear()
            is_plugin = path.endswith(".mll")
            self._plugin_cmd_label.setVisible(is_plugin)
            self._plugin_cmd_input.setVisible(is_plugin)
            if is_plugin:
                # Binary plugin — no functions to list, hide run mode options
                self._mode_group.setVisible(False)
            elif path.endswith(".py"):
                funcs = list_functions(path)
                if funcs:
                    self._func_combo.addItems(funcs)
                    self._func_combo.setCurrentIndex(0)
            elif path.endswith(".pyc"):
                # Bytecode — can't introspect; user types the function name.
                self._func_combo.setEditText("show")
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
        namespace = slugify_namespace(self._namespace_input.text())

        # Reject names that aren't valid Python identifiers when the
        # entry point will go through importlib. Single-file MEL / .mll
        # / exec-mode files are exempt because they don't import.
        if not self._validate_import_target(path, is_exec_mode):
            return

        if self._is_folder:
            info = getattr(self, "_detected_info", None)
            # Maya module: type already determined, no entry_point
            if info and info.get("is_maya_module"):
                self._result = {
                    "file_path": path,
                    "namespace": namespace,
                    "name": slugify_name(info.get("name", "")),
                    "display_name": display_name,
                    "version": "0.0.0",
                    "author": "",
                    "icon": icon,
                    "description": description,
                    "type": "maya_module",
                    "entry_point": {},
                    "is_folder": True,
                }
                self.accept()
                return
            # If package.json exists, use its entry_point directly
            if info and info.get("has_package_json"):
                result = {
                    "file_path": path,
                    "namespace": namespace or slugify_namespace(info.get("namespace", "")),
                    "name": slugify_name(info.get("name", "")),
                    "display_name": display_name,
                    "version": info.get("version", "0.0.0"),
                    "author": info.get("author", ""),
                    "icon": icon,
                    "description": description,
                    "type": info.get("type", "python_package"),
                    "entry_point": info.get("entry_point", {}),
                    "is_folder": True,
                }
                if info.get("home_registry"):
                    result["home_registry"] = info["home_registry"]
                self._result = result
                self.accept()
                return
            self._result = self._build_folder_result(path, display_name, func, icon, description)
            self._result["namespace"] = namespace
        else:
            self._result = self._build_file_result(path, display_name, func, icon, description, is_exec_mode)
            self._result["namespace"] = namespace
            # Carry sidecar's home_registry forward if present
            sidecar = (getattr(self, "_detected_info", None) or {}).get("sidecar")
            if sidecar and sidecar.get("home_registry"):
                self._result["home_registry"] = sidecar["home_registry"]

        self.accept()

    def _validate_import_target(self, path, is_exec_mode):
        """Refuse names that importlib can't load.

        Returns True if the registration may proceed. On failure, shows
        a message box pointing the user at what to rename and returns
        False.
        """
        if self._is_folder:
            info = getattr(self, "_detected_info", None) or _detect_from_folder(path)
            # maya_module / package.json folders bring their own naming;
            # we trust them.
            if info.get("is_maya_module") or info.get("has_package_json"):
                return True
            if info.get("type") != "python_package":
                return True
            module_name = info.get("name") or os.path.basename(path)
        else:
            # Single file: only python imports go through importlib.
            if is_exec_mode:
                return True
            if path.endswith((".mel", ".mll")):
                return True
            module_name = os.path.splitext(os.path.basename(path))[0]

        if is_valid_python_module_name(module_name):
            return True

        QtWidgets.QMessageBox.warning(
            self, "Carton",
            t("add_invalid_module_name", module_name),
        )
        return False

    def _build_file_result(self, path, display_name, func, icon, description, is_exec_mode):
        raw_basename = os.path.splitext(os.path.basename(path))[0]
        slug = slugify_name(raw_basename) or raw_basename.lower()
        # Import target keeps the original casing so importlib finds the
        # actual file on case-sensitive filesystems (macOS / Linux). The
        # slug is identity only.
        module_name = raw_basename
        is_mel = path.endswith(".mel")
        is_plugin = path.endswith(".mll")

        if is_plugin:
            entry_point = {
                "type": "plugin",
                "file": os.path.basename(path),
            }
            plugin_cmd = self._plugin_cmd_input.text().strip()
            if plugin_cmd:
                entry_point["command"] = plugin_cmd
            pkg_type = "plugin"
        elif is_exec_mode:
            entry_point = {
                "type": "exec",
                "file": os.path.basename(path),
            }
            pkg_type = "mel_script" if is_mel else "python_package"
        elif is_mel:
            entry_point = {
                "type": "mel",
                "script": os.path.basename(path),
                "procedure": func or module_name,
            }
            pkg_type = "mel_script"
        else:
            entry_point = {
                "type": "python",
                "module": module_name,
                "function": func or "show",
            }
            pkg_type = "python_package"

        return {
            "file_path": path,
            "name": slug,
            "display_name": display_name,
            "icon": icon,
            "description": description,
            "type": pkg_type,
            "entry_point": entry_point,
            "is_folder": False,
        }

    def _build_folder_result(self, path, display_name, func, icon, description):
        info = _detect_from_folder(path)
        raw_name = info["name"]
        slug = slugify_name(raw_name) or raw_name.lower()
        # Same split as files: slug = identity, raw_name = import target.
        module_name = raw_name
        pkg_type = info["type"]

        if pkg_type == "mel_script":
            # MEL folder: find the first .mel in scripts/
            mel_files = []
            scripts_dir = os.path.join(path, "scripts")
            search_dir = scripts_dir if os.path.isdir(scripts_dir) else path
            for f in os.listdir(search_dir):
                if f.endswith(".mel"):
                    mel_files.append(f)
            script_file = mel_files[0] if mel_files else "{}.mel".format(module_name)
            entry_point = {
                "type": "mel",
                "script": script_file,
                "procedure": func or os.path.splitext(script_file)[0],
            }
        else:
            entry_point = {
                "type": "python",
                "module": module_name,
                "function": func or "show",
            }

        return {
            "file_path": path,
            "name": slug,
            "display_name": display_name,
            "icon": icon,
            "description": description,
            "type": pkg_type,
            "entry_point": entry_point,
            "is_folder": True,
            "include_compiled": bool(info.get("include_compiled", False)),
        }

    def get_result(self):
        return self._result

    @classmethod
    def prompt(cls, parent=None):
        dialog = cls(parent)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            return dialog.get_result()
        return None
