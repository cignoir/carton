"""Dialog for editing metadata of local tools."""

import os

from carton.ui.compat import QtWidgets, QtCore, Qt
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.utils import list_functions
from carton.ui._dialog_widgets import (
    make_dim_label, make_readonly_input, make_namespace_preview_label,
    update_namespace_preview, make_icon_row, browse_icon_into,
)
from carton.core.identity import slugify_namespace


class EditDialog(QtWidgets.QDialog):
    """Dialog for editing metadata of locally registered tools."""

    def __init__(self, pkg_id, pkg_data, published_catalogues=None, parent=None):
        super().__init__(parent)
        self._pkg_id = pkg_id
        self._pkg_data = pkg_data
        self._published_catalogues = published_catalogues or []
        self._result = None

        self.setWindowTitle(t("edit_title"))
        self.setMinimumSize(460, 640)
        self.resize(460, 680)
        self.setStyleSheet(
            theme.dialog_style(
                theme.combobox_style()
                + "QRadioButton {{ color: {text}; font-size: 13px; }}".format(
                    text=theme.TEXT_PRIMARY)
            )
        )

        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)

        # Display Name
        self._name_input = QtWidgets.QLineEdit(self._pkg_data.get("display_name", ""))
        form.addRow(make_dim_label(t("label_display_name")), self._name_input)

        # Name (slug) — read-only. Changing this would orphan the registry
        # entry, so it can only be set during Add.
        self._slug_display = make_readonly_input(
            self._pkg_data.get("name", ""), tooltip=t("name_tooltip"),
        )
        form.addRow(
            make_dim_label(t("label_name"), tooltip=t("name_tooltip")),
            self._slug_display,
        )

        # Namespace (locked once the package has been published, since renaming
        # would orphan the registry entry)
        self._namespace_input = QtWidgets.QLineEdit(self._pkg_data.get("namespace", ""))
        self._namespace_input.setPlaceholderText(t("namespace_placeholder"))
        self._namespace_input.textChanged.connect(self._update_namespace_preview)
        # "Published" for namespace-lock purposes: known to live in any
        # writable registry. The publisher resolves the "is it actually
        # there" question for us via published_catalogues; we don't need
        # to second-guess based on installed.json source flags.
        is_published = bool(self._published_catalogues)
        if is_published:
            self._namespace_input.setReadOnly(True)
            self._namespace_input.setToolTip(
                "Locked: this package is already published. "
                "Unpublish first to change the namespace."
            )
            self._namespace_input.setStyleSheet(
                self._namespace_input.styleSheet() + " color: {};".format(theme.TEXT_DIM)
            )
        form.addRow(make_dim_label(t("label_namespace")), self._namespace_input)
        # Slug preview on its own row to keep the input from being squished
        self._namespace_preview = make_namespace_preview_label()
        form.addRow("", self._namespace_preview)

        # Version
        self._ver_input = QtWidgets.QLineEdit(self._pkg_data.get("version", "0.0.0"))
        form.addRow(make_dim_label(t("label_version")), self._ver_input)

        # Icon
        icon_row, self._icon_input = make_icon_row(
            self._pkg_data.get("icon", "🔧"), self._browse_icon,
        )
        form.addRow(make_dim_label(t("label_icon")), icon_row)

        # Homepage
        self._homepage_input = QtWidgets.QLineEdit(self._pkg_data.get("homepage", ""))
        self._homepage_input.setPlaceholderText("https://...")
        form.addRow(make_dim_label(t("label_homepage")), self._homepage_input)

        # Author
        self._author_input = QtWidgets.QLineEdit(self._pkg_data.get("author", ""))
        form.addRow(make_dim_label(t("label_author")), self._author_input)

        # Description
        self._desc_input = QtWidgets.QLineEdit(self._pkg_data.get("description", ""))
        form.addRow(make_dim_label(t("label_description")), self._desc_input)

        # Local Path (read-only)
        local_path = self._pkg_data.get("local_path", "")
        if local_path:
            form.addRow(
                make_dim_label(t("label_path")),
                make_readonly_input(local_path),
            )

        layout.addLayout(form)

        # Run Mode
        entry = self._pkg_data.get("entry_point", {})
        ep_type = entry.get("type", "python")

        mode_group = QtWidgets.QGroupBox(t("label_run_mode"))
        mode_group.setStyleSheet(theme.groupbox_style())
        mode_layout = QtWidgets.QVBoxLayout(mode_group)

        self._mode_exec = QtWidgets.QRadioButton(t("add_exec_mode"))
        mode_layout.addWidget(self._mode_exec)

        self._mode_func = QtWidgets.QRadioButton(t("add_func_mode"))
        mode_func_layout = QtWidgets.QHBoxLayout()
        mode_func_layout.addWidget(self._mode_func)
        self._func_combo = QtWidgets.QComboBox()
        self._func_combo.setEditable(True)
        mode_func_layout.addWidget(self._func_combo)
        mode_layout.addLayout(mode_func_layout)

        # Module override — only meaningful for folder packages where the
        # importable target may differ from the folder name (e.g. a
        # ``scripts/`` folder containing standalone tools where the
        # entry point is ``import genimport`` rather than ``import scripts``).
        self._module_label = QtWidgets.QLabel(t("edit_module_name"))
        self._module_label.setStyleSheet(theme.LABEL_DIM)
        self._module_input = QtWidgets.QLineEdit(entry.get("module", ""))
        self._module_input.setPlaceholderText("e.g. genimport")
        mode_layout.addWidget(self._module_label)
        mode_layout.addWidget(self._module_input)
        if not self._pkg_data.get("is_folder") or ep_type != "python":
            self._module_label.setVisible(False)
            self._module_input.setVisible(False)

        # Populate function list in dropdown
        if local_path and os.path.isfile(local_path) and local_path.endswith(".py"):
            funcs = list_functions(local_path)
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

        # Maya modules don't have a launchable entry point by default — hide
        # the run mode group entirely.
        if self._pkg_data.get("type") == "maya_module" and not entry:
            mode_group.setVisible(False)

        # Plugin command (also reused for maya_module launch commands).
        self._is_plugin = (ep_type == "plugin"
                           or (local_path and local_path.endswith(".mll")))
        self._is_module = (self._pkg_data.get("type") == "maya_module")
        self._plugin_cmd_label = QtWidgets.QLabel(
            t("label_launch_command") if self._is_module else t("label_plugin_command")
        )
        self._plugin_cmd_label.setStyleSheet(theme.LABEL_DIM)
        self._plugin_cmd_input = QtWidgets.QLineEdit(entry.get("command", ""))
        if self._is_module:
            self._plugin_cmd_input.setPlaceholderText(
                "from siweighteditor.siweighteditor import WeightEditorWindow; WeightEditorWindow()"
            )
            self._plugin_cmd_input.setToolTip(t("launch_command_tooltip"))
        else:
            self._plugin_cmd_input.setPlaceholderText(
                "import maya.cmds as mc; mc.exAttrEditor(ui=True)"
            )
        layout.addWidget(self._plugin_cmd_label)
        layout.addWidget(self._plugin_cmd_input)

        if self._is_plugin or self._is_module:
            mode_group.setVisible(False)
        else:
            self._plugin_cmd_label.setVisible(False)
            self._plugin_cmd_input.setVisible(False)

        layout.addStretch()

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()

        # Remove button (left-aligned)
        remove_btn = QtWidgets.QPushButton(t("remove"))
        remove_btn.setStyleSheet(theme.btn_danger())
        remove_btn.clicked.connect(self._on_remove)
        btn_layout.addWidget(remove_btn)

        if self._published_catalogues:
            history_btn = QtWidgets.QPushButton(t("show_history"))
            history_btn.setStyleSheet(theme.btn_ghost_text())
            history_btn.clicked.connect(self._on_history)
            btn_layout.addWidget(history_btn)

            unpub_btn = QtWidgets.QPushButton(t("unpublish"))
            unpub_btn.setStyleSheet(theme.btn_warning())
            unpub_btn.clicked.connect(self._on_unpublish)
            btn_layout.addWidget(unpub_btn)

        btn_layout.addStretch()

        cancel_btn = QtWidgets.QPushButton(t("cancel"))
        cancel_btn.setStyleSheet(theme.btn_ghost())
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QtWidgets.QPushButton(t("save"))
        save_btn.setStyleSheet(theme.btn_primary())
        save_btn.clicked.connect(self._on_save)
        save_btn.setDefault(True)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _update_namespace_preview(self, text):
        update_namespace_preview(self._namespace_preview, text)

    def _browse_icon(self):
        browse_icon_into(self, self._icon_input)

    def _on_save(self):
        display_name = self._name_input.text().strip()
        if not display_name:
            QtWidgets.QMessageBox.warning(self, "Carton", t("add_no_display_name"))
            return

        name = self._pkg_data.get("name", "")
        local_path = self._pkg_data.get("local_path", "")
        is_mel = local_path.endswith(".mel")

        if self._is_module:
            # Maya module: entry_point carries only the optional launch command.
            cmd = self._plugin_cmd_input.text().strip()
            entry_point = {"command": cmd} if cmd else {}
        elif self._is_plugin:
            entry_point = {
                "type": "plugin",
                "file": os.path.basename(local_path),
            }
            cmd = self._plugin_cmd_input.text().strip()
            if cmd:
                entry_point["command"] = cmd
        elif self._mode_exec.isChecked():
            entry_point = {
                "type": "exec",
                "file": os.path.basename(local_path),
            }
        elif is_mel:
            entry_point = {
                "type": "mel",
                "script": os.path.basename(self._pkg_data.get("local_path", "")),
                "procedure": self._func_combo.currentText().strip() or name,
            }
        else:
            override = self._module_input.text().strip()
            entry_point = {
                "type": "python",
                "module": override or name,
                "function": self._func_combo.currentText().strip() or "show",
            }

        self._result = {
            "action": "save",
            "display_name": display_name,
            "version": self._ver_input.text().strip() or "0.0.0",
            "author": self._author_input.text().strip(),
            "icon": self._icon_input.text().strip() or "🔧",
            "homepage": self._homepage_input.text().strip(),
            "description": self._desc_input.text().strip(),
            # Round-trip the auto-detected flag without exposing it in UI.
            "include_compiled": bool(self._pkg_data.get("include_compiled", False)),
            "entry_point": entry_point,
            "namespace": slugify_namespace(self._namespace_input.text()),
        }
        self.accept()

    def _on_remove(self):
        display = self._pkg_data.get("display_name", self._pkg_id)
        reply = QtWidgets.QMessageBox.question(
            self, "Remove",
            t("edit_confirm_remove", display),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self._result = {"action": "remove"}
            self.accept()

    def _on_history(self):
        # Hand off to main_window — it owns the registry client and can
        # render the version history with full version info.
        self._result = {"action": "history"}
        self.accept()

    def _on_unpublish(self):
        display = self._pkg_data.get("display_name", self._pkg_id)
        regs = self._published_catalogues

        if len(regs) == 1:
            target = regs[0]
        else:
            names = [r.name for r in regs]
            chosen, ok = QtWidgets.QInputDialog.getItem(
                self, t("unpublish"), t("unpublish_select_catalogue"),
                names, 0, False,
            )
            if not ok:
                return
            target = next(r for r in regs if r.name == chosen)

        reply = QtWidgets.QMessageBox.question(
            self, t("unpublish"),
            t("confirm_unpublish", display, target.name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self._result = {"action": "unpublish", "catalogue": target}
            self.accept()

    def get_result(self):
        return self._result

    @classmethod
    def prompt(cls, pkg_id, pkg_data, published_catalogues=None, parent=None):
        dialog = cls(pkg_id, pkg_data, published_catalogues=published_catalogues, parent=parent)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            return dialog.get_result()
        return None
