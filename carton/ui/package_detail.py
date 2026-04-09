"""Package detail panel — rich layout for registry packages."""

import os

from carton.ui.compat import QtWidgets, QtCore, QtGui, Qt
from carton.ui.i18n import t
from carton.ui.package_card import TypeBadge
from carton.ui import theme


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
    rollback_requested = QtCore.Signal(str, str)  # (pkg_id, version)
    back_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pkg_id = ""
        self._homepage = ""
        self._setup_ui()

    # ── Style constants (kept aligned with theme.py vocabulary) ──
    _LABEL_STYLE = (
        "color: {muted}; font-size: 11px; font-weight: 600;"
        " background: transparent;"
    ).format(muted=theme.TEXT_MUTED)
    _VALUE_STYLE = (
        "color: {dim}; font-size: 12px; background: transparent;"
    ).format(dim=theme.TEXT_SECONDARY)

    def _setup_ui(self):
        # Outer layout: just hosts a scroll area so the panel can scroll
        # when its content exceeds the available height.
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        outer.addWidget(scroll)

        inner = QtWidgets.QWidget()
        scroll.setWidget(inner)

        layout = QtWidgets.QVBoxLayout(inner)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        # Back button
        back_btn = QtWidgets.QPushButton(t("back"))
        back_btn.setFlat(True)
        back_btn.setStyleSheet(
            "QPushButton {{ color: {dim}; font-size: 12px; text-align: left;"
            "  background: transparent; border: none; padding: 0; }}"
            "QPushButton:hover {{ color: {text}; }}".format(
                dim=theme.TEXT_DIM, text=theme.TEXT_PRIMARY)
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
            "QLabel {{ background: {bg}; border-radius: 12px; }}".format(bg=theme.BG_SECONDARY)
        )
        hero.addWidget(self._icon_label, 0, Qt.AlignTop)

        # Title block
        title_block = QtWidgets.QVBoxLayout()
        title_block.setSpacing(6)

        # Name row
        name_row = QtWidgets.QHBoxLayout()
        name_row.setSpacing(8)
        self._name_label = QtWidgets.QLabel()
        self._name_label.setStyleSheet(
            "font-size: 20px; font-weight: 600; color: {}; background: transparent;".format(
                theme.TEXT_HEADING)
        )
        name_row.addWidget(self._name_label)

        self._badge_container = QtWidgets.QHBoxLayout()
        self._badge_container.setSpacing(0)
        self._badge_container.setContentsMargins(0, 0, 0, 0)
        name_row.addLayout(self._badge_container)
        name_row.addStretch()
        title_block.addLayout(name_row)

        # Author + version subtitle (rich text so we can highlight "update available")
        self._subtitle_label = QtWidgets.QLabel()
        self._subtitle_label.setTextFormat(Qt.RichText)
        self._subtitle_label.setStyleSheet(
            "font-size: 12px; color: {}; background: transparent;".format(theme.TEXT_DIM)
        )
        title_block.addWidget(self._subtitle_label)

        hero.addLayout(title_block, stretch=1)

        # Action buttons: primary on top, secondary row below
        action_col = QtWidgets.QVBoxLayout()
        action_col.setSpacing(8)
        action_col.setAlignment(Qt.AlignTop)

        self._action_btn = QtWidgets.QPushButton()
        self._action_btn.setFixedWidth(120)
        self._action_btn.setFixedHeight(36)
        action_col.addWidget(self._action_btn)

        self._uninstall_btn = QtWidgets.QPushButton(t("uninstall"))
        self._uninstall_btn.setFixedWidth(120)
        self._uninstall_btn.setStyleSheet(
            "QPushButton {{ color: {red}; background: transparent; border: 1px solid {border};"
            "  border-radius: 6px; padding: 6px 4px; font-size: 11px; }}"
            "QPushButton:hover {{ background: {red_bg}; border-color: {red}; }}".format(
                red=theme.ACCENT_RED, border=theme.BORDER, red_bg=theme.ACCENT_RED_BG)
        )
        self._uninstall_btn.clicked.connect(
            lambda: self.uninstall_requested.emit(self._pkg_id)
        )
        action_col.addWidget(self._uninstall_btn)

        self._history_btn = QtWidgets.QPushButton(t("show_history"))
        self._history_btn.setFixedWidth(120)
        self._history_btn.setStyleSheet(
            "QPushButton {{ color: {dim}; background: transparent;"
            "  border: 1px solid {border}; border-radius: 6px;"
            "  padding: 6px 4px; font-size: 11px; }}"
            "QPushButton:hover {{ color: {text}; border-color: {border_h}; }}".format(
                dim=theme.TEXT_SECONDARY, text=theme.TEXT_PRIMARY,
                border=theme.BORDER, border_h=theme.BORDER_HOVER)
        )
        self._history_btn.clicked.connect(self._open_history)
        action_col.addWidget(self._history_btn)

        hero.addLayout(action_col)
        layout.addLayout(hero)

        layout.addSpacing(16)

        # ── Description ──
        self._desc_label = QtWidgets.QLabel()
        self._desc_label.setStyleSheet(
            "font-size: 13px; color: {}; background: transparent;"
            "  line-height: 1.5;".format(theme.TEXT_PRIMARY)
        )
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)

        layout.addSpacing(16)

        # ── Homepage link ──
        self._homepage_btn = QtWidgets.QPushButton()
        self._homepage_btn.setFlat(True)
        self._homepage_btn.setStyleSheet(theme.btn_link())
        self._homepage_btn.setCursor(Qt.PointingHandCursor)
        self._homepage_btn.clicked.connect(self._open_homepage)
        layout.addWidget(self._homepage_btn)

        layout.addSpacing(16)

        # ── Separator ──
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: {};".format(theme.BORDER))
        layout.addWidget(sep)

        layout.addSpacing(16)

        # ── Info grid: 2 columns of stacked label/value blocks ──
        info_grid = QtWidgets.QGridLayout()
        info_grid.setHorizontalSpacing(32)
        info_grid.setVerticalSpacing(14)
        info_grid.setContentsMargins(0, 0, 0, 0)

        self._type_val = self._make_value_label()
        info_grid.addLayout(
            self._make_field(t("label_type"), self._type_val), 0, 0)

        self._maya_val = self._make_value_label()
        info_grid.addLayout(
            self._make_field(t("label_maya"), self._maya_val), 0, 1)

        self._size_val = self._make_value_label()
        info_grid.addLayout(
            self._make_field(t("label_size"), self._size_val), 1, 0)

        self._released_val = self._make_value_label()
        info_grid.addLayout(
            self._make_field(t("label_released"), self._released_val), 1, 1)

        info_grid.setColumnStretch(0, 1)
        info_grid.setColumnStretch(1, 1)

        layout.addLayout(info_grid)

        # ── Tags section ──
        layout.addSpacing(16)
        self._tags_section = QtWidgets.QWidget()
        tags_layout = QtWidgets.QVBoxLayout(self._tags_section)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(6)
        tags_layout.addWidget(self._make_label(t("label_tags"), self._LABEL_STYLE))
        self._tags_container = QtWidgets.QWidget()
        self._tags_layout = QtWidgets.QVBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(4)
        tags_layout.addWidget(self._tags_container)
        layout.addWidget(self._tags_section)

        # ── Changelog section ──
        layout.addSpacing(16)
        self._changelog_section = QtWidgets.QWidget()
        cl_layout = QtWidgets.QVBoxLayout(self._changelog_section)
        cl_layout.setContentsMargins(0, 0, 0, 0)
        cl_layout.setSpacing(6)
        cl_layout.addWidget(self._make_label(t("label_changelog"), self._LABEL_STYLE))
        self._changelog_val = QtWidgets.QLabel()
        self._changelog_val.setStyleSheet(self._VALUE_STYLE)
        self._changelog_val.setWordWrap(True)
        cl_layout.addWidget(self._changelog_val)
        layout.addWidget(self._changelog_section)

        layout.addStretch()

    def _make_value_label(self):
        lbl = QtWidgets.QLabel()
        lbl.setStyleSheet(self._VALUE_STYLE)
        lbl.setWordWrap(True)
        return lbl

    def _make_field(self, label_text, value_widget):
        """Stack a small label above its value."""
        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(self._make_label(label_text, self._LABEL_STYLE))
        col.addWidget(value_widget)
        return col

    @staticmethod
    def _make_chip(text):
        """Pill-shaped tag chip — visual matches package_card.TypeBadge family."""
        chip = QtWidgets.QLabel(text)
        chip.setStyleSheet(
            "QLabel {{"
            "  background: transparent;"
            "  color: {color};"
            "  border: 1px solid {border};"
            "  border-radius: 9px;"
            "  padding: 1px 8px;"
            "  font-size: 10px;"
            "}}".format(color=theme.TEXT_SECONDARY, border=theme.BORDER)
        )
        chip.setAlignment(Qt.AlignCenter)
        return chip

    def _set_tags(self, tags):
        # Clear previous rows
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                child = item.layout()
                if child is not None:
                    while child.count():
                        ci = child.takeAt(0)
                        if ci.widget():
                            ci.widget().deleteLater()
                    child.deleteLater()

        if not tags:
            self._tags_section.setVisible(False)
            return
        self._tags_section.setVisible(True)

        # Build rows of chips. We don't have FlowLayout in Qt stdlib,
        # so we approximate with fixed chips per row based on text length.
        row = None
        row_budget = 0
        max_row_chars = 60
        for tag in tags:
            chip_cost = len(tag) + 4
            if row is None or row_budget + chip_cost > max_row_chars:
                row = QtWidgets.QHBoxLayout()
                row.setSpacing(6)
                row.setContentsMargins(0, 0, 0, 0)
                self._tags_layout.addLayout(row)
                row_budget = 0
                # add stretch at end after we finish populating; instead push items left
            row.addWidget(self._make_chip(tag))
            row_budget += chip_cost
            # ensure trailing stretch on the row
            # (re-add stretch by appending after last item — Qt allows multiple stretches harmlessly)
        # Append a stretch to each row so chips left-align
        for i in range(self._tags_layout.count()):
            item = self._tags_layout.itemAt(i)
            lay = item.layout()
            if lay is not None:
                lay.addStretch()

    @staticmethod
    def _make_label(text, style):
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(style)
        return lbl

    def _open_homepage(self):
        if self._homepage:
            import webbrowser
            webbrowser.open(self._homepage)

    def _open_history(self):
        if not getattr(self, "_registry_data", None):
            return
        from carton.ui.version_history_dialog import VersionHistoryDialog
        dlg = VersionHistoryDialog(
            self._pkg_id, self._registry_data,
            self._installed_version, parent=self,
        )
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            chosen = dlg.chosen_version()
            if chosen:
                self.rollback_requested.emit(self._pkg_id, chosen)

    def show_package(self, pkg_id, registry_data, installed_version=None,
                     icon_path=None):
        """Display package information."""
        self._pkg_id = pkg_id
        self._registry_data = registry_data
        self._installed_version = installed_version
        pkg_type = registry_data.get("type", "python_package")
        latest = registry_data.get("latest_version", "")
        version_info = registry_data.get("versions", {}).get(latest, {})

        # Icon
        self._icon_label.setPixmap(QtGui.QPixmap())  # Clear
        self._icon_label.setText("")
        _detail_icon_style = (
            "QLabel {{ background: {bg}; border-radius: 12px; font-size: 28px; }}".format(
                bg=theme.BG_SECONDARY)
        )
        icon_value = registry_data.get("icon", "")

        if icon_path and os.path.exists(icon_path):
            pixmap = QtGui.QPixmap(icon_path)
            self._icon_label.setPixmap(
                pixmap.scaled(52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._icon_label.setStyleSheet(
                "QLabel {{ background: {bg}; border-radius: 12px; }}".format(
                    bg=theme.BG_SECONDARY)
            )
        elif (isinstance(icon_value, str) and icon_value
                and icon_value not in ("true", "false")
                and not icon_value.endswith((".png", ".jpg", ".svg"))):
            self._icon_label.setText(icon_value)
            self._icon_label.setStyleSheet(_detail_icon_style)
        else:
            self._icon_label.setStyleSheet(_detail_icon_style)
            self._icon_label.setText("\U0001f4e6")

        # Name
        self._name_label.setText(registry_data.get("display_name", pkg_id))

        # Badge
        while self._badge_container.count():
            item = self._badge_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._badge_container.addWidget(TypeBadge(pkg_type))

        # Subtitle: author + version (rich text; highlight "update available")
        author = registry_data.get("author", "")
        if installed_version:
            ver_text = "v{}".format(installed_version)
            if latest and latest != installed_version:
                ver_text += (
                    '  &rarr;  <span style="color:{c};">v{v} available</span>'
                ).format(c=theme.ACCENT_ORANGE, v=latest)
        else:
            ver_text = "v{}".format(latest) if latest else ""
        subtitle_parts = []
        if author:
            from html import escape as _esc
            subtitle_parts.append(_esc(author))
        if ver_text:
            subtitle_parts.append(ver_text)
        self._subtitle_label.setText("  &middot;  ".join(subtitle_parts))

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
        self._set_tags(registry_data.get("tags", []) or [])
        changelog_text = version_info.get("changelog", "") or ""
        if changelog_text.strip():
            self._changelog_val.setText(changelog_text)
            self._changelog_section.setVisible(True)
        else:
            self._changelog_section.setVisible(False)

        # Action button
        # Safely reconnect action button
        try:
            self._action_btn.clicked.disconnect()
        except RuntimeError:
            pass

        if installed_version:
            self._action_btn.setText(t("launch"))
            self._action_btn.setStyleSheet(
                theme.btn_card_action(theme.ACCENT_BLUE, theme.ACCENT_BLUE_HOVER,
                                      radius=6, padding=8, font_size=13)
            )
            self._action_btn.clicked.connect(
                lambda: self.launch_requested.emit(self._pkg_id)
            )
            self._uninstall_btn.setVisible(True)
        else:
            self._action_btn.setText(t("install"))
            self._action_btn.setStyleSheet(
                theme.btn_card_action(theme.ACCENT_GREEN, theme.ACCENT_GREEN_HOVER,
                                      text_color=theme.BG_PRIMARY,
                                      radius=6, padding=8, font_size=13)
            )
            self._action_btn.clicked.connect(
                lambda: self.install_requested.emit(self._pkg_id)
            )
            self._uninstall_btn.setVisible(False)
