"""Package detail panel."""

from carton.ui.compat import QtWidgets, QtCore, Qt
from carton.ui.i18n import t
from carton.ui.package_card import TypeBadge


class PackageDetailPanel(QtWidgets.QWidget):
    """Panel for displaying package detail information."""

    install_requested = QtCore.Signal(str)
    uninstall_requested = QtCore.Signal(str)
    launch_requested = QtCore.Signal(str)
    back_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pkg_id = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Back button
        back_btn = QtWidgets.QPushButton(t("back"))
        back_btn.setFlat(True)
        back_btn.setStyleSheet(
            "QPushButton { color: #666; font-size: 12px; text-align: left;"
            "  background: transparent; border: none; }"
            "QPushButton:hover { color: #a0a0a0; }"
        )
        back_btn.clicked.connect(self.back_requested.emit)
        layout.addWidget(back_btn)

        # Header
        header = QtWidgets.QHBoxLayout()
        self._name_label = QtWidgets.QLabel()
        self._name_label.setStyleSheet("font-size: 20px; font-weight: 600; color: #e0e0e0; background: transparent;")
        header.addWidget(self._name_label)

        self._badge_container = QtWidgets.QHBoxLayout()
        header.addLayout(self._badge_container)
        header.addStretch()

        self._action_btn = QtWidgets.QPushButton()
        self._action_btn.setFixedWidth(100)
        header.addWidget(self._action_btn)

        layout.addLayout(header)

        # Version
        self._version_label = QtWidgets.QLabel()
        self._version_label.setStyleSheet("font-size: 12px; color: #666; background: transparent;")
        layout.addWidget(self._version_label)

        # Description
        self._desc_label = QtWidgets.QLabel()
        self._desc_label.setStyleSheet("font-size: 13px; color: #b0b0b0; background: transparent;")
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)

        # Metadata
        self._meta_area = QtWidgets.QWidget()
        self._meta_area.setStyleSheet("background: transparent;")
        meta_layout = QtWidgets.QFormLayout(self._meta_area)
        meta_layout.setContentsMargins(0, 12, 0, 0)
        meta_layout.setVerticalSpacing(8)
        label_style = "color: #666; font-size: 12px; background: transparent;"
        value_style = "color: #a0a0a0; font-size: 12px; background: transparent;"

        self._author_val = QtWidgets.QLabel()
        self._author_val.setStyleSheet(value_style)
        author_label = QtWidgets.QLabel(t("label_author"))
        author_label.setStyleSheet(label_style)
        meta_layout.addRow(author_label, self._author_val)

        self._maya_val = QtWidgets.QLabel()
        self._maya_val.setStyleSheet(value_style)
        maya_label = QtWidgets.QLabel(t("label_maya"))
        maya_label.setStyleSheet(label_style)
        meta_layout.addRow(maya_label, self._maya_val)

        self._tags_val = QtWidgets.QLabel()
        self._tags_val.setStyleSheet(value_style)
        tags_label = QtWidgets.QLabel(t("label_tags"))
        tags_label.setStyleSheet(label_style)
        meta_layout.addRow(tags_label, self._tags_val)

        self._changelog_val = QtWidgets.QLabel()
        self._changelog_val.setStyleSheet(value_style)
        self._changelog_val.setWordWrap(True)
        changelog_label = QtWidgets.QLabel(t("label_changelog"))
        changelog_label.setStyleSheet(label_style)
        meta_layout.addRow(changelog_label, self._changelog_val)

        layout.addWidget(self._meta_area)
        layout.addStretch()

        # Uninstall
        self._uninstall_btn = QtWidgets.QPushButton(t("uninstall"))
        self._uninstall_btn.setStyleSheet(
            "QPushButton { color: #e57373; background: transparent; border: 1px solid #4a2a2a;"
            "  border-radius: 6px; padding: 8px; font-size: 12px; }"
            "QPushButton:hover { background: #2e1e1e; border-color: #e57373; }"
        )
        self._uninstall_btn.clicked.connect(
            lambda: self.uninstall_requested.emit(self._pkg_id)
        )
        layout.addWidget(self._uninstall_btn)

    def show_package(self, pkg_id, registry_data, installed_version=None):
        """Display package information."""
        self._pkg_id = pkg_id
        pkg_type = registry_data.get("type", "python_package")
        latest = registry_data.get("latest_version", "")

        self._name_label.setText(registry_data.get("display_name", pkg_id))

        # Replace badge
        while self._badge_container.count():
            item = self._badge_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._badge_container.addWidget(TypeBadge(pkg_type))

        # Version
        if installed_version:
            ver = "Installed: v{}".format(installed_version)
            if latest and latest != installed_version:
                ver += "  (v{} available)".format(latest)
        else:
            ver = "Latest: v{}".format(latest) if latest else ""
        self._version_label.setText(ver)

        self._desc_label.setText(registry_data.get("description", ""))
        self._author_val.setText(registry_data.get("author", ""))

        # Get Maya versions from version info
        version_info = registry_data.get("versions", {}).get(latest, {})
        self._maya_val.setText(", ".join(version_info.get("maya_versions", [])))
        self._tags_val.setText(", ".join(registry_data.get("tags", [])))
        self._changelog_val.setText(version_info.get("changelog", ""))

        # Button configuration
        if installed_version:
            self._action_btn.setText(t("launch"))
            self._action_btn.setStyleSheet(
                "QPushButton { background: #3572A5; color: white; border: none;"
                "  border-radius: 6px; padding: 8px; font-weight: 600; font-size: 13px; }"
                "QPushButton:hover { background: #4080b8; }"
            )
            try:
                self._action_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self._action_btn.clicked.connect(
                lambda: self.launch_requested.emit(self._pkg_id)
            )
            self._uninstall_btn.setVisible(True)
        else:
            self._action_btn.setText(t("install"))
            self._action_btn.setStyleSheet(
                "QPushButton { background: #4CAF50; color: #1e1e1e; border: none;"
                "  border-radius: 6px; padding: 8px; font-weight: 600; font-size: 13px; }"
                "QPushButton:hover { background: #5cbf60; }"
            )
            try:
                self._action_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self._action_btn.clicked.connect(
                lambda: self.install_requested.emit(self._pkg_id)
            )
            self._uninstall_btn.setVisible(False)
