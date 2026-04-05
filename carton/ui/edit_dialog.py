"""Dialog for editing metadata of local tools."""

import os

from carton.ui.compat import QtWidgets, QtCore, Qt
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.utils import list_functions


class EditDialog(QtWidgets.QDialog):
    """Dialog for editing metadata of locally registered tools."""

    def __init__(self, pkg_id, pkg_data, published_registries=None, parent=None):
        super().__init__(parent)
        self._pkg_id = pkg_id
        self._pkg_data = pkg_data
        self._published_registries = published_registries or []
        self._result = None

        self.setWindowTitle(t("edit_title"))
        self.setFixedSize(440, 480)
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
        name_label = QtWidgets.QLabel(t("label_display_name"))
        name_label.setStyleSheet(theme.LABEL_DIM)
        self._name_input = QtWidgets.QLineEdit(self._pkg_data.get("display_name", ""))
        form.addRow(name_label, self._name_input)

        # Version
        ver_label = QtWidgets.QLabel(t("label_version"))
        ver_label.setStyleSheet(theme.LABEL_DIM)
        self._ver_input = QtWidgets.QLineEdit(self._pkg_data.get("version", "0.0.0"))
        form.addRow(ver_label, self._ver_input)

        # Icon
        icon_label = QtWidgets.QLabel(t("label_icon"))
        icon_label.setStyleSheet(theme.LABEL_DIM)
        icon_row = QtWidgets.QHBoxLayout()
        self._icon_input = QtWidgets.QLineEdit(self._pkg_data.get("icon", "🔧"))
        icon_row.addWidget(self._icon_input)
        icon_browse_btn = QtWidgets.QPushButton(t("file"))
        icon_browse_btn.setFixedWidth(60)
        icon_browse_btn.setStyleSheet(theme.btn_small_browse())
        icon_browse_btn.clicked.connect(self._browse_icon)
        icon_row.addWidget(icon_browse_btn)
        form.addRow(icon_label, icon_row)

        # Homepage
        homepage_label = QtWidgets.QLabel(t("label_homepage"))
        homepage_label.setStyleSheet(theme.LABEL_DIM)
        self._homepage_input = QtWidgets.QLineEdit(self._pkg_data.get("homepage", ""))
        self._homepage_input.setPlaceholderText("https://...")
        form.addRow(homepage_label, self._homepage_input)

        # Author
        author_label = QtWidgets.QLabel(t("label_author"))
        author_label.setStyleSheet(theme.LABEL_DIM)
        self._author_input = QtWidgets.QLineEdit(self._pkg_data.get("author", ""))
        form.addRow(author_label, self._author_input)

        # Description
        desc_label = QtWidgets.QLabel(t("label_description"))
        desc_label.setStyleSheet(theme.LABEL_DIM)
        self._desc_input = QtWidgets.QLineEdit(self._pkg_data.get("description", ""))
        form.addRow(desc_label, self._desc_input)

        # Local Path (read-only)
        local_path = self._pkg_data.get("local_path", "")
        if local_path:
            path_label = QtWidgets.QLabel(t("label_path"))
            path_label.setStyleSheet(theme.LABEL_DIM)
            path_val = QtWidgets.QLineEdit(local_path)
            path_val.setReadOnly(True)
            path_val.setStyleSheet(path_val.styleSheet() + " color: {};".format(theme.TEXT_DIM))
            form.addRow(path_label, path_val)

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
        layout.addStretch()

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()

        # Remove button (left-aligned)
        remove_btn = QtWidgets.QPushButton(t("remove"))
        remove_btn.setStyleSheet(theme.btn_danger())
        remove_btn.clicked.connect(self._on_remove)
        btn_layout.addWidget(remove_btn)

        if self._published_registries:
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

    def _browse_icon(self):
        path = QtWidgets.QFileDialog.getOpenFileName(
            self, t("label_icon"), "",
            "Images (*.png *.jpg *.svg);;All (*)",
        )[0]
        if path:
            self._icon_input.setText(path)

    def _on_save(self):
        display_name = self._name_input.text().strip()
        if not display_name:
            QtWidgets.QMessageBox.warning(self, "Carton", t("add_no_display_name"))
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
            "author": self._author_input.text().strip(),
            "icon": self._icon_input.text().strip() or "🔧",
            "homepage": self._homepage_input.text().strip(),
            "description": self._desc_input.text().strip(),
            "entry_point": entry_point,
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

    def _on_unpublish(self):
        display = self._pkg_data.get("display_name", self._pkg_id)
        regs = self._published_registries

        if len(regs) == 1:
            target = regs[0]
        else:
            names = [r.name for r in regs]
            chosen, ok = QtWidgets.QInputDialog.getItem(
                self, t("unpublish"), t("unpublish_select_registry"),
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
            self._result = {"action": "unpublish", "registry": target}
            self.accept()

    def get_result(self):
        return self._result

    @classmethod
    def prompt(cls, pkg_id, pkg_data, published_registries=None, parent=None):
        dialog = cls(pkg_id, pkg_data, published_registries=published_registries, parent=parent)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            return dialog.get_result()
        return None
