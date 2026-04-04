"""Package detail panel — rich layout for registry packages."""

import os

from carton.ui.compat import QtWidgets, QtCore, QtGui, Qt
from carton.ui.i18n import t
from carton.ui.package_card import TypeBadge


def _format_size(size_bytes):
    """Format bytes into human-readable string."""
    if not size_bytes:
        return ""
    if size_bytes < 1024:
        return "{} B".format(size_bytes)
    elif size_bytes < 1024 * 1024:
        return "{:.1f} KB".format(size_bytes / 1024)
    else:
        return "{:.1f} MB".format(size_bytes / (1024 * 1024))


def _format_date(date_str):
    """Format ISO date string to readable date."""
    if not date_str:
        return ""
    return date_str[:10]  # YYYY-MM-DD


class PackageDetailPanel(QtWidgets.QWidget):
    """Panel for displaying package detail information."""

    install_requested = QtCore.Signal(str)
    uninstall_requested = QtCore.Signal(str)
    launch_requested = QtCore.Signal(str)
    back_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pkg_id = ""
        self._homepage = ""
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        # Back button
        back_btn = QtWidgets.QPushButton(t("back"))
        back_btn.setFlat(True)
        back_btn.setStyleSheet(
            "QPushButton { color: #5c6370; font-size: 12px; text-align: left;"
            "  background: transparent; border: none; padding: 0; }"
            "QPushButton:hover { color: #abb2bf; }"
        )
        back_btn.clicked.connect(self.back_requested.emit)
        layout.addWidget(back_btn)

        layout.addSpacing(12)

        # ── Hero section: icon + name + badge + action ──
        hero = QtWidgets.QHBoxLayout()
        hero.setSpacing(16)

        self._icon_label = QtWidgets.QLabel()
        self._icon_label.setFixedSize(64, 64)
        self._icon_label.setAlignment(Qt.AlignCenter)
        self._icon_label.setStyleSheet(
            "QLabel { background: #1d1f23; border-radius: 12px; }"
        )
        hero.addWidget(self._icon_label)

        # Title block
        title_block = QtWidgets.QVBoxLayout()
        title_block.setSpacing(4)

        # Name row
        name_row = QtWidgets.QHBoxLayout()
        name_row.setSpacing(8)
        self._name_label = QtWidgets.QLabel()
        self._name_label.setStyleSheet(
            "font-size: 20px; font-weight: 600; color: #d7dae0; background: transparent;"
        )
        name_row.addWidget(self._name_label)

        self._badge_container = QtWidgets.QHBoxLayout()
        name_row.addLayout(self._badge_container)
        name_row.addStretch()
        title_block.addLayout(name_row)

        # Author + version subtitle
        self._subtitle_label = QtWidgets.QLabel()
        self._subtitle_label.setStyleSheet(
            "font-size: 12px; color: #5c6370; background: transparent;"
        )
        title_block.addWidget(self._subtitle_label)

        hero.addLayout(title_block, stretch=1)

        # Action buttons (vertical stack)
        action_col = QtWidgets.QVBoxLayout()
        action_col.setSpacing(6)

        self._action_btn = QtWidgets.QPushButton()
        self._action_btn.setFixedWidth(120)
        self._action_btn.setFixedHeight(36)
        action_col.addWidget(self._action_btn)

        self._uninstall_btn = QtWidgets.QPushButton(t("uninstall"))
        self._uninstall_btn.setFixedWidth(120)
        self._uninstall_btn.setStyleSheet(
            "QPushButton { color: #e06c75; background: transparent; border: 1px solid #3e4452;"
            "  border-radius: 6px; padding: 6px; font-size: 11px; }"
            "QPushButton:hover { background: #382025; border-color: #e06c75; }"
        )
        self._uninstall_btn.clicked.connect(
            lambda: self.uninstall_requested.emit(self._pkg_id)
        )
        action_col.addWidget(self._uninstall_btn)

        hero.addLayout(action_col)
        layout.addLayout(hero)

        layout.addSpacing(16)

        # ── Description ──
        self._desc_label = QtWidgets.QLabel()
        self._desc_label.setStyleSheet(
            "font-size: 13px; color: #abb2bf; background: transparent;"
            "  line-height: 1.5;"
        )
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)

        layout.addSpacing(16)

        # ── Homepage link ──
        self._homepage_btn = QtWidgets.QPushButton()
        self._homepage_btn.setFlat(True)
        self._homepage_btn.setStyleSheet(
            "QPushButton { color: #61afef; font-size: 12px; text-align: left;"
            "  background: transparent; border: none; padding: 0;"
            "  text-decoration: underline; }"
            "QPushButton:hover { color: #8bc4f7; }"
        )
        self._homepage_btn.setCursor(Qt.PointingHandCursor)
        self._homepage_btn.clicked.connect(self._open_homepage)
        layout.addWidget(self._homepage_btn)

        layout.addSpacing(16)

        # ── Separator ──
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #3e4452;")
        layout.addWidget(sep)

        layout.addSpacing(12)

        # ── Info grid ──
        info_grid = QtWidgets.QGridLayout()
        info_grid.setHorizontalSpacing(24)
        info_grid.setVerticalSpacing(8)

        label_style = "color: #495162; font-size: 11px; font-weight: 600; background: transparent;"
        value_style = "color: #7f848e; font-size: 12px; background: transparent;"

        # Row 0: Type | Maya
        info_grid.addWidget(self._make_label(t("label_type"), label_style), 0, 0)
        self._type_val = QtWidgets.QLabel()
        self._type_val.setStyleSheet(value_style)
        info_grid.addWidget(self._type_val, 0, 1)

        info_grid.addWidget(self._make_label(t("label_maya"), label_style), 0, 2)
        self._maya_val = QtWidgets.QLabel()
        self._maya_val.setStyleSheet(value_style)
        info_grid.addWidget(self._maya_val, 0, 3)

        # Row 1: Size | Released
        info_grid.addWidget(self._make_label(t("label_size"), label_style), 1, 0)
        self._size_val = QtWidgets.QLabel()
        self._size_val.setStyleSheet(value_style)
        info_grid.addWidget(self._size_val, 1, 1)

        info_grid.addWidget(self._make_label(t("label_released"), label_style), 1, 2)
        self._released_val = QtWidgets.QLabel()
        self._released_val.setStyleSheet(value_style)
        info_grid.addWidget(self._released_val, 1, 3)

        # Row 2: Tags (full width)
        info_grid.addWidget(self._make_label(t("label_tags"), label_style), 2, 0)
        self._tags_val = QtWidgets.QLabel()
        self._tags_val.setStyleSheet(value_style)
        self._tags_val.setWordWrap(True)
        info_grid.addWidget(self._tags_val, 2, 1, 1, 3)

        # Row 3: Changelog (full width)
        info_grid.addWidget(self._make_label(t("label_changelog"), label_style), 3, 0, Qt.AlignTop)
        self._changelog_val = QtWidgets.QLabel()
        self._changelog_val.setStyleSheet(value_style)
        self._changelog_val.setWordWrap(True)
        info_grid.addWidget(self._changelog_val, 3, 1, 1, 3)

        info_grid.setColumnStretch(1, 1)
        info_grid.setColumnStretch(3, 1)

        layout.addLayout(info_grid)
        layout.addStretch()

    @staticmethod
    def _make_label(text, style):
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    def _open_homepage(self):
        if self._homepage:
            import webbrowser
            webbrowser.open(self._homepage)

    def show_package(self, pkg_id, registry_data, installed_version=None):
        """Display package information."""
        self._pkg_id = pkg_id
        pkg_type = registry_data.get("type", "python_package")
        latest = registry_data.get("latest_version", "")
        version_info = registry_data.get("versions", {}).get(latest, {})

        # Icon
        self._icon_label.setPixmap(QtGui.QPixmap())  # Clear
        self._icon_label.setText("")
        icon_value = registry_data.get("icon", "")
        if isinstance(icon_value, str) and icon_value and icon_value not in ("true", "false") and not icon_value.endswith((".png", ".jpg", ".svg")):
            self._icon_label.setText(icon_value)
            self._icon_label.setStyleSheet(
                "QLabel { background: #1d1f23; border-radius: 12px; font-size: 28px; }"
            )
        else:
            self._icon_label.setStyleSheet(
                "QLabel { background: #1d1f23; border-radius: 12px; font-size: 28px; }"
            )
            self._icon_label.setText("📦")

        # Name
        self._name_label.setText(registry_data.get("display_name", pkg_id))

        # Badge
        while self._badge_container.count():
            item = self._badge_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._badge_container.addWidget(TypeBadge(pkg_type))

        # Subtitle: author + version
        author = registry_data.get("author", "")
        if installed_version:
            ver_text = "v{}".format(installed_version)
            if latest and latest != installed_version:
                ver_text += "  →  v{} available".format(latest)
        else:
            ver_text = "v{}".format(latest) if latest else ""
        subtitle_parts = []
        if author:
            subtitle_parts.append(author)
        if ver_text:
            subtitle_parts.append(ver_text)
        self._subtitle_label.setText("  ·  ".join(subtitle_parts))

        # Description
        self._desc_label.setText(registry_data.get("description", ""))

        # Homepage
        self._homepage = registry_data.get("homepage", "")
        if self._homepage:
            self._homepage_btn.setText(self._homepage)
            self._homepage_btn.setVisible(True)
        else:
            self._homepage_btn.setVisible(False)

        # Info grid
        type_labels = {
            "python_package": "Python Package",
            "mel_script": "MEL Script",
            "plugin": "Plugin",
        }
        self._type_val.setText(type_labels.get(pkg_type, pkg_type))
        self._maya_val.setText(", ".join(version_info.get("maya_versions", [])))
        self._size_val.setText(_format_size(version_info.get("size_bytes")))
        self._released_val.setText(_format_date(version_info.get("released_at", "")))
        self._tags_val.setText(", ".join(registry_data.get("tags", [])))
        self._changelog_val.setText(version_info.get("changelog", "") or "—")

        # Action button
        if installed_version:
            self._action_btn.setText(t("launch"))
            self._action_btn.setStyleSheet(
                "QPushButton { background: #4d78cc; color: white; border: none;"
                "  border-radius: 6px; padding: 8px; font-weight: 600; font-size: 13px; }"
                "QPushButton:hover { background: #5a8ae6; }"
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
                "QPushButton { background: #98c379; color: #282c34; border: none;"
                "  border-radius: 6px; padding: 8px; font-weight: 600; font-size: 13px; }"
                "QPushButton:hover { background: #a9d487; }"
            )
            try:
                self._action_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self._action_btn.clicked.connect(
                lambda: self.install_requested.emit(self._pkg_id)
            )
            self._uninstall_btn.setVisible(False)
