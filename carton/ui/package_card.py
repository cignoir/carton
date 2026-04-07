"""Package card widget."""

import os

from carton.ui.compat import QtWidgets, QtCore, QtGui, Qt
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.utils import resolve_icon

_DEFAULT_ICON = None


def _get_default_icon_path():
    """Return the path to the default icon."""
    return os.path.join(
        os.path.dirname(__file__), "resources", "icons", "default_package.png"
    )

# Badge configuration per type
_BADGE_CONFIG = {
    "python_package": ("PY", theme.ACCENT_BLUE),
    "mel_script": ("MEL", theme.ACCENT_GREEN),
    "plugin": ("PLG", theme.ACCENT_ORANGE),
    "maya_module": ("MOD", theme.ACCENT_LINK),
    "local": ("LOCAL", theme.TEXT_DIM),
}


class TypeBadge(QtWidgets.QLabel):
    """Type badge."""

    def __init__(self, pkg_type, parent=None):
        super().__init__(parent)
        label, color = _BADGE_CONFIG.get(pkg_type, ("?", theme.TEXT_DIM))
        self.setText(label)
        self.setFixedHeight(18)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "QLabel {{"
            "  background-color: transparent;"
            "  color: {color};"
            "  border: 1px solid {color};"
            "  border-radius: 3px;"
            "  padding: 0px 5px;"
            "  font-size: 10px;"
            "  font-weight: 600;"
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
    unpublish_requested = QtCore.Signal(str, str)  # (pkg_id, registry_name)

    def __init__(self, pkg_id, pkg_data, installed_version=None, icon_path=None,
                 published_registries=None, parent=None):
        super().__init__(parent)
        self._pkg_id = pkg_id
        self._pkg_data = pkg_data
        self._installed_version = installed_version
        self._icon_path = icon_path
        self._published_registries = list(published_registries or [])
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setStyleSheet(
            "PackageCard {{"
            "  background: {bg};"
            "  border: 1px solid {border};"
            "  border-radius: 8px;"
            "}}"
            "PackageCard:hover {{"
            "  background: {hover};"
            "  border-color: {border_hover};"
            "}}".format(bg=theme.BG_SECONDARY, border=theme.BORDER_LIGHT,
                        hover=theme.BG_HOVER, border_hover=theme.BORDER_HOVER)
        )
        self.setFixedHeight(80)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        # Icon
        self._icon_label = QtWidgets.QLabel()
        self._icon_label.setFixedSize(48, 48)
        self._icon_label.setStyleSheet(
            "QLabel { background: transparent; border-radius: 8px; }"
        )
        self._icon_label.setAlignment(Qt.AlignCenter)
        icon_value = self._pkg_data.get("icon", "")

        # Resolve icon source: icon_path (from registry), direct file path, emoji, or default
        resolved_path = self._icon_path
        if not resolved_path and isinstance(icon_value, str) and icon_value.endswith((".png", ".jpg", ".svg")):
            if os.path.isabs(icon_value) and os.path.exists(icon_value):
                resolved_path = icon_value

        resolve_icon(self._icon_label, icon_value, resolved_path,
                     size=40, default_icon_path=_get_default_icon_path())
        layout.addWidget(self._icon_label)

        # Info
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setSpacing(4)

        # Title row
        title_layout = QtWidgets.QHBoxLayout()
        title_layout.setSpacing(8)

        name_label = QtWidgets.QLabel(self._pkg_data.get("display_name", self._pkg_id))
        name_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: {}; background: transparent;".format(
                theme.TEXT_HEADING)
        )
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
        ver_label.setStyleSheet(
            "font-size: 11px; color: {}; background: transparent;".format(theme.TEXT_DIM)
        )
        title_layout.addWidget(ver_label)

        # Pinned badge — version held intentionally after a rollback.
        if self._installed_version and self._pkg_data.get("pinned"):
            pin_label = QtWidgets.QLabel("\U0001f4cc " + t("pinned_badge"))
            pin_label.setToolTip(t("pinned_badge_tooltip"))
            pin_label.setStyleSheet(
                "font-size: 10px; font-weight: 600; color: {color};"
                " background: transparent; padding: 1px 6px;"
                " border: 1px solid {color}; border-radius: 3px;".format(
                    color=theme.ACCENT_ORANGE)
            )
            title_layout.addWidget(pin_label)

        # Verified badge — installed packages whose registry entry carried a
        # sha256 (and therefore had it checked at download time).
        if self._installed_version and self._pkg_data.get("sha256"):
            verified = QtWidgets.QLabel("\u2713 " + t("verified_badge"))
            verified.setToolTip(t("verified_badge_tooltip"))
            verified.setStyleSheet(
                "font-size: 10px; font-weight: 600; color: {color};"
                " background: transparent; padding: 1px 6px;"
                " border: 1px solid {color}; border-radius: 3px;".format(
                    color=theme.ACCENT_GREEN)
            )
            title_layout.addWidget(verified)

        # Published-to badge: clickable menu for unpublish, shown when this
        # package currently lives in one or more writable local registries.
        if self._published_registries:
            pub_btn = QtWidgets.QToolButton()
            if len(self._published_registries) == 1:
                pub_btn.setText(t("published_to_badge", self._published_registries[0]))
            else:
                pub_btn.setText(t("published_to_badge_multi", len(self._published_registries)))
            pub_btn.setToolTip(t("unpublish_select_registry"))
            pub_btn.setCursor(Qt.PointingHandCursor)
            pub_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            pub_btn.setStyleSheet(
                "QToolButton {{"
                "  background: transparent;"
                "  color: {color};"
                "  border: 1px solid {color};"
                "  border-radius: 3px;"
                "  padding: 1px 6px;"
                "  font-size: 10px;"
                "  font-weight: 600;"
                "}}"
                "QToolButton:hover {{ background: {hover}; }}"
                "QToolButton::menu-indicator {{ image: none; width: 0; }}".format(
                    color=theme.ACCENT_GREEN, hover=theme.BG_HOVER)
            )
            menu = QtWidgets.QMenu(pub_btn)
            # QMenu inherits the dialog palette by default and gives no hover
            # feedback on items — style it explicitly so the unpublish action
            # highlights on mouseover.
            menu.setStyleSheet(
                "QMenu {{"
                "  background: {bg};"
                "  color: {text};"
                "  border: 1px solid {border};"
                "  padding: 4px 0;"
                "}}"
                "QMenu::item {{"
                "  background: transparent;"
                "  padding: 6px 16px;"
                "}}"
                "QMenu::item:selected {{"
                "  background: {hover};"
                "  color: {accent};"
                "}}".format(
                    bg=theme.BG_SECONDARY,
                    text=theme.TEXT_SECONDARY,
                    border=theme.BORDER_HOVER,
                    hover=theme.BG_HOVER,
                    accent=theme.ACCENT_GREEN,
                )
            )
            for reg_name in self._published_registries:
                act = menu.addAction(t("unpublish_from", reg_name))
                # Default-arg binding to freeze reg_name per iteration.
                act.triggered.connect(
                    lambda checked=False, r=reg_name: self.unpublish_requested.emit(
                        self._pkg_id, r)
                )
            pub_btn.setMenu(menu)
            title_layout.addWidget(pub_btn)

        title_layout.addStretch()

        author = self._pkg_data.get("author", "")
        if author:
            author_label = QtWidgets.QLabel(author)
            author_label.setStyleSheet(
                "font-size: 11px; color: {}; background: transparent;".format(theme.TEXT_MUTED)
            )
            title_layout.addWidget(author_label)

        info_layout.addLayout(title_layout)

        # Description
        desc = self._pkg_data.get("description", "")
        desc_label = QtWidgets.QLabel(desc)
        desc_label.setStyleSheet(
            "font-size: 12px; color: {}; background: transparent;".format(theme.TEXT_SECONDARY)
        )
        desc_label.setWordWrap(True)
        info_layout.addWidget(desc_label)

        layout.addLayout(info_layout, stretch=1)

        # Right: buttons
        btn_layout = QtWidgets.QVBoxLayout()
        btn_layout.setAlignment(Qt.AlignCenter)

        is_local = self._pkg_data.get("_local_script", False)

        is_pinned = bool(self._pkg_data.get("pinned"))

        if self._installed_version or is_local:
            # Determine if an update is available. Pinned packages are
            # held intentionally (after a rollback), so the Update button
            # is suppressed even if a newer version exists.
            has_update = False
            latest = self._pkg_data.get("latest_version", "")
            if latest and latest != self._installed_version and not is_local and not is_pinned:
                try:
                    from carton.models.version import Version
                    has_update = Version.parse(latest) > Version.parse(self._installed_version)
                except ValueError:
                    pass

            if has_update:
                update_btn = QtWidgets.QPushButton(t("update"))
                update_btn.setFixedWidth(80)
                update_btn.setStyleSheet(
                    theme.btn_card_action(theme.ACCENT_ORANGE, theme.ACCENT_ORANGE_HOVER,
                                          text_color=theme.BG_PRIMARY)
                )
                update_btn.clicked.connect(lambda: self.update_requested.emit(self._pkg_id))
                btn_layout.addWidget(update_btn)

            # Maya modules without an explicit entry point use "Activate"
            # since there's no single window to launch — clicking just
            # re-runs userSetup.py.
            is_module = (self._pkg_data.get("type") == "maya_module"
                         and not self._pkg_data.get("entry_point"))
            launch_btn = QtWidgets.QPushButton(
                t("activate") if is_module else t("launch")
            )
            launch_btn.setFixedWidth(80)
            launch_btn.setStyleSheet(
                theme.btn_card_action(theme.ACCENT_BLUE, theme.ACCENT_BLUE_HOVER)
            )
            launch_btn.clicked.connect(lambda: self.launch_requested.emit(self._pkg_id))
            btn_layout.addWidget(launch_btn)

            if is_local:
                publish_btn = QtWidgets.QPushButton(t("publish"))
                publish_btn.setFixedWidth(80)
                publish_btn.setStyleSheet(
                    theme.btn_card_outlined(theme.ACCENT_GREEN, "#5c7a4e", "#2a3325")
                )
                publish_btn.clicked.connect(lambda: self.publish_requested.emit(self._pkg_id))
                btn_layout.addWidget(publish_btn)
        else:
            install_btn = QtWidgets.QPushButton(t("install"))
            install_btn.setFixedWidth(80)
            install_btn.setStyleSheet(
                theme.btn_card_action(theme.ACCENT_GREEN, theme.ACCENT_GREEN_HOVER,
                                      text_color=theme.BG_PRIMARY)
            )
            install_btn.clicked.connect(lambda: self.install_requested.emit(self._pkg_id))
            btn_layout.addWidget(install_btn)

        layout.addLayout(btn_layout)

    def set_icon(self, icon_path):
        """Update the icon after initial construction (e.g. async download)."""
        if icon_path and os.path.exists(icon_path):
            resolve_icon(self._icon_label, None, icon_path, size=40)
