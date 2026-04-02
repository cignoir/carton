"""Package detail panel."""

from carton.ui.compat import QtWidgets, QtCore, Qt
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
        back_btn = QtWidgets.QPushButton("← Back")
        back_btn.setFlat(True)
        back_btn.setStyleSheet("color: #888; font-size: 12px; text-align: left;")
        back_btn.clicked.connect(self.back_requested.emit)
        layout.addWidget(back_btn)

        # Header
        header = QtWidgets.QHBoxLayout()
        self._name_label = QtWidgets.QLabel()
        self._name_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #e0e0e0;")
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
        self._version_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self._version_label)

        # Description
        self._desc_label = QtWidgets.QLabel()
        self._desc_label.setStyleSheet("font-size: 13px; color: #ccc;")
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)

        # Metadata
        self._meta_area = QtWidgets.QWidget()
        meta_layout = QtWidgets.QFormLayout(self._meta_area)
        meta_layout.setContentsMargins(0, 8, 0, 0)
        label_style = "color: #888; font-size: 12px;"
        value_style = "color: #ccc; font-size: 12px;"

        self._author_val = QtWidgets.QLabel()
        self._author_val.setStyleSheet(value_style)
        author_label = QtWidgets.QLabel("Author")
        author_label.setStyleSheet(label_style)
        meta_layout.addRow(author_label, self._author_val)

        self._maya_val = QtWidgets.QLabel()
        self._maya_val.setStyleSheet(value_style)
        maya_label = QtWidgets.QLabel("Maya")
        maya_label.setStyleSheet(label_style)
        meta_layout.addRow(maya_label, self._maya_val)

        self._tags_val = QtWidgets.QLabel()
        self._tags_val.setStyleSheet(value_style)
        tags_label = QtWidgets.QLabel("Tags")
        tags_label.setStyleSheet(label_style)
        meta_layout.addRow(tags_label, self._tags_val)

        self._changelog_val = QtWidgets.QLabel()
        self._changelog_val.setStyleSheet(value_style)
        self._changelog_val.setWordWrap(True)
        changelog_label = QtWidgets.QLabel("Changelog")
        changelog_label.setStyleSheet(label_style)
        meta_layout.addRow(changelog_label, self._changelog_val)

        layout.addWidget(self._meta_area)
        layout.addStretch()

        # Uninstall
        self._uninstall_btn = QtWidgets.QPushButton("Uninstall")
        self._uninstall_btn.setStyleSheet(
            "QPushButton { color: #e57373; background: transparent; border: 1px solid #e57373;"
            "  border-radius: 4px; padding: 6px; }"
            "QPushButton:hover { background: #3c2020; }"
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
            self._action_btn.setText("Launch")
            self._action_btn.setStyleSheet(
                "QPushButton { background: #3572A5; color: white; border: none;"
                "  border-radius: 4px; padding: 8px; }"
                "QPushButton:hover { background: #4682B5; }"
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
            self._action_btn.setText("Install")
            self._action_btn.setStyleSheet(
                "QPushButton { background: #4CAF50; color: white; border: none;"
                "  border-radius: 4px; padding: 8px; }"
                "QPushButton:hover { background: #5CBF60; }"
            )
            try:
                self._action_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self._action_btn.clicked.connect(
                lambda: self.install_requested.emit(self._pkg_id)
            )
            self._uninstall_btn.setVisible(False)
