"""Package card widget."""

import os

from carton.ui.compat import QtWidgets, QtCore, QtGui, Qt

_DEFAULT_ICON = None


def _get_default_icon_path():
    """Return the path to the default icon."""
    return os.path.join(
        os.path.dirname(__file__), "resources", "icons", "default_package.png"
    )

# Badge configuration per type
_BADGE_CONFIG = {
    "python_package": ("PY", "#3572A5"),
    "mel_script": ("MEL", "#4CAF50"),
    "plugin": ("PLG", "#FF9800"),
    "local": ("LOCAL", "#9E9E9E"),
}


class TypeBadge(QtWidgets.QLabel):
    """Type badge."""

    def __init__(self, pkg_type, parent=None):
        super().__init__(parent)
        label, color = _BADGE_CONFIG.get(pkg_type, ("?", "#666"))
        self.setText(label)
        self.setFixedHeight(20)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "QLabel {{"
            "  background-color: {color};"
            "  color: white;"
            "  border-radius: 3px;"
            "  padding: 0px 6px;"
            "  font-size: 11px;"
            "  font-weight: bold;"
            "}}".format(color=color)
        )
        self.adjustSize()


class PackageCard(QtWidgets.QFrame):
    """Card widget displayed in the package list."""

    launch_requested = QtCore.Signal(str)
    install_requested = QtCore.Signal(str)
    uninstall_requested = QtCore.Signal(str)
    publish_requested = QtCore.Signal(str)
    update_requested = QtCore.Signal(str)

    def __init__(self, pkg_id, pkg_data, installed_version=None, icon_path=None, parent=None):
        super().__init__(parent)
        self._pkg_id = pkg_id
        self._pkg_data = pkg_data
        self._installed_version = installed_version
        self._icon_path = icon_path
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setStyleSheet(
            "PackageCard {"
            "  background: #2b2b2b;"
            "  border: 1px solid #3c3c3c;"
            "  border-radius: 6px;"
            "}"
            "PackageCard:hover {"
            "  border-color: #5c5c5c;"
            "}"
        )
        self.setFixedHeight(80)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        # Icon
        self._icon_label = QtWidgets.QLabel()
        self._icon_label.setFixedSize(48, 48)
        self._icon_label.setStyleSheet(
            "QLabel { background: #383838; border-radius: 6px; }"
        )
        self._icon_label.setAlignment(Qt.AlignCenter)
        icon_value = self._pkg_data.get("icon", "")
        if isinstance(icon_value, str) and icon_value and not icon_value.endswith((".png", ".jpg", ".svg")) and icon_value not in ("true", "false"):
            # Emoji icon
            self._icon_label.setText(icon_value)
            self._icon_label.setStyleSheet(
                "QLabel { background: #383838; border-radius: 6px;"
                "  font-size: 24px; }"
            )
        elif self._icon_path and os.path.exists(self._icon_path):
            pixmap = QtGui.QPixmap(self._icon_path)
            self._icon_label.setPixmap(
                pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            # Default icon
            default = _get_default_icon_path()
            if os.path.exists(default):
                pixmap = QtGui.QPixmap(default)
                self._icon_label.setPixmap(
                    pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            else:
                self._icon_label.setText("📦")
                self._icon_label.setStyleSheet(
                    "QLabel { background: #383838; border-radius: 6px;"
                    "  font-size: 24px; }"
                )
        layout.addWidget(self._icon_label)

        # Info
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setSpacing(4)

        # Title row
        title_layout = QtWidgets.QHBoxLayout()
        title_layout.setSpacing(8)

        name_label = QtWidgets.QLabel(self._pkg_data.get("display_name", self._pkg_id))
        name_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #e0e0e0;")
        title_layout.addWidget(name_label)

        badge = TypeBadge(self._pkg_data.get("type", "python_package"))
        title_layout.addWidget(badge)

        # Version
        latest = self._pkg_data.get("latest_version", "")
        is_local = self._pkg_data.get("_local_script", False)
        if self._installed_version:
            ver_text = "v{}".format(self._installed_version)
            if not is_local and latest and latest != self._installed_version:
                ver_text += " → v{}".format(latest)
        else:
            ver_text = "v{}".format(latest) if latest else ""

        ver_label = QtWidgets.QLabel(ver_text)
        ver_label.setStyleSheet("font-size: 11px; color: #888;")
        title_layout.addWidget(ver_label)
        title_layout.addStretch()

        info_layout.addLayout(title_layout)

        # Description
        desc = self._pkg_data.get("description", "")
        desc_label = QtWidgets.QLabel(desc)
        desc_label.setStyleSheet("font-size: 12px; color: #aaa;")
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)

        layout.addLayout(info_layout, stretch=1)

        # Right: buttons
        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setAlignment(Qt.AlignCenter)

        is_local = self._pkg_data.get("_local_script", False)

        if self._installed_version:
            # Determine if an update is available
            has_update = False
            latest = self._pkg_data.get("latest_version", "")
            if latest and latest != self._installed_version and not is_local:
                try:
                    from carton.models.version import Version
                    has_update = Version.parse(latest) > Version.parse(self._installed_version)
                except ValueError:
                    pass

            if has_update:
                update_btn = QtWidgets.QPushButton("Update")
                update_btn.setFixedWidth(80)
                update_btn.setStyleSheet(
                    "QPushButton {"
                    "  background: #FF9800; color: white; border: none;"
                    "  border-radius: 4px; padding: 6px;"
                    "}"
                    "QPushButton:hover { background: #FFA826; }"
                )
                update_btn.clicked.connect(lambda: self.update_requested.emit(self._pkg_id))
                btn_layout.addWidget(update_btn)

            launch_btn = QtWidgets.QPushButton("Launch")
            launch_btn.setFixedWidth(80)
            launch_btn.setStyleSheet(
                "QPushButton {"
                "  background: #3572A5; color: white; border: none;"
                "  border-radius: 4px; padding: 6px;"
                "}"
                "QPushButton:hover { background: #4682B5; }"
            )
            launch_btn.clicked.connect(lambda: self.launch_requested.emit(self._pkg_id))
            btn_layout.addWidget(launch_btn)

            if is_local:
                publish_btn = QtWidgets.QPushButton("Publish")
                publish_btn.setFixedWidth(80)
                publish_btn.setStyleSheet(
                    "QPushButton {"
                    "  background: transparent; color: #4CAF50;"
                    "  border: 1px solid #4CAF50; border-radius: 4px; padding: 4px;"
                    "  font-size: 11px;"
                    "}"
                    "QPushButton:hover { background: #1b3a1b; }"
                )
                publish_btn.clicked.connect(lambda: self.publish_requested.emit(self._pkg_id))
                btn_layout.addWidget(publish_btn)
        else:
            install_btn = QtWidgets.QPushButton("Install")
            install_btn.setFixedWidth(80)
            install_btn.setStyleSheet(
                "QPushButton {"
                "  background: #4CAF50; color: white; border: none;"
                "  border-radius: 4px; padding: 6px;"
                "}"
                "QPushButton:hover { background: #5CBF60; }"
            )
            install_btn.clicked.connect(lambda: self.install_requested.emit(self._pkg_id))
            btn_layout.addWidget(install_btn)

        layout.addLayout(btn_layout)
