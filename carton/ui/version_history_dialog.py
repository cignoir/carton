"""Version history browser with rollback support."""

from carton.ui.compat import QtWidgets, Qt
from carton.ui.i18n import t
from carton.ui import theme


def _format_date(iso):
    if not iso:
        return ""
    return iso.split("T")[0]


class VersionHistoryDialog(QtWidgets.QDialog):
    """List every published version of a package; offer rollback.

    Versions are sorted newest-first using semver where possible.
    Each row shows the release date, version label, latest/installed
    markers, the release notes, and a Rollback button (disabled for the
    currently installed version).
    """

    def __init__(self, pkg_id, pkg_data, installed_version, parent=None):
        super().__init__(parent)
        self._pkg_id = pkg_id
        self._installed_version = installed_version or ""
        self._chosen_version = None  # set when the user clicks Rollback

        self.setWindowTitle(t("version_history_title", pkg_data.get("display_name", "")))
        self.setMinimumSize(560, 480)
        # Apply dialog base + slim scrollbar styling consistent with MAIN_STYLE
        scrollbar_extra = (
            "QScrollArea {{ border: none; background: transparent; }}"
            "QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}"
            "QScrollBar::handle:vertical {{"
            "  background: {handle}; border-radius: 4px; min-height: 30px;"
            "}}"
            "QScrollBar::handle:vertical:hover {{ background: {handle_h}; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}"
        ).format(handle=theme.SCROLLBAR_HANDLE, handle_h=theme.SCROLLBAR_HANDLE_HOVER)
        self.setStyleSheet(theme.dialog_style(extra=scrollbar_extra))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        hint = QtWidgets.QLabel(t("version_history_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
        layout.addWidget(hint)

        layout.addWidget(self._h_separator())

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        container = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)

        latest = pkg_data.get("latest_version", "")
        versions = pkg_data.get("versions", {}) or {}
        for ver in self._sorted_versions(versions.keys()):
            info = versions.get(ver, {}) or {}
            col.addWidget(self._make_row(ver, info, latest))
        col.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        layout.addWidget(self._h_separator())

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        close = QtWidgets.QPushButton(t("close"))
        close.setStyleSheet(theme.btn_ghost())
        close.clicked.connect(self.reject)
        btn_row.addWidget(close)
        layout.addLayout(btn_row)

    @staticmethod
    def _h_separator():
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: {}; border: none;".format(theme.BORDER_LIGHT))
        return sep

    @staticmethod
    def _sorted_versions(version_keys):
        """Newest first; fall back to lexical when semver parse fails."""
        from carton.models.version import Version
        keys = list(version_keys)
        try:
            return sorted(keys, key=Version.parse, reverse=True)
        except ValueError:
            return sorted(keys, reverse=True)

    def _make_row(self, version, info, latest):
        is_installed = (version == self._installed_version)
        row = QtWidgets.QFrame()
        if is_installed:
            row.setObjectName("versionRowInstalled")
            row.setStyleSheet(
                "#versionRowInstalled {{"
                "  background: {bg}; border: 1px solid {border};"
                "  border-radius: 6px;"
                "}}".format(bg=theme.BG_HOVER, border=theme.BORDER_HOVER)
            )
        else:
            row.setObjectName("versionRow")
            row.setStyleSheet(
                "#versionRow {{"
                "  background: {bg}; border: 1px solid {border};"
                "  border-radius: 6px;"
                "}}"
                "#versionRow:hover {{ border-color: {border_h}; }}".format(
                    bg=theme.BG_SECONDARY, border=theme.BORDER,
                    border_h=theme.BORDER_HOVER)
            )
        rl = QtWidgets.QVBoxLayout(row)
        rl.setContentsMargins(14, 12, 14, 12)
        rl.setSpacing(8)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(10)
        head.setAlignment(Qt.AlignVCenter)

        ver_label = QtWidgets.QLabel("v{}".format(version))
        ver_label.setStyleSheet(
            "font-weight: 700; font-size: 13px; color: {}; background: transparent;".format(
                theme.TEXT_PRIMARY)
        )
        head.addWidget(ver_label)

        if version == latest:
            head.addWidget(self._tag(t("version_history_latest"), theme.ACCENT_GREEN))
        if is_installed:
            head.addWidget(self._tag(t("version_history_installed"), theme.ACCENT_BLUE))

        head.addStretch(1)

        date = _format_date(info.get("released_at", ""))
        if date:
            d = QtWidgets.QLabel(date)
            d.setStyleSheet(
                "color: {}; font-size: 11px; background: transparent;".format(theme.TEXT_MUTED)
            )
            head.addWidget(d)

        rollback = QtWidgets.QPushButton(t("version_history_rollback"))
        rollback.setStyleSheet(
            "QPushButton {{"
            "  color: {text}; background: transparent;"
            "  border: 1px solid {border}; border-radius: 4px;"
            "  padding: 4px 10px; font-size: 11px;"
            "}}"
            "QPushButton:hover {{ background: {bg_h}; border-color: {border_h}; }}"
            "QPushButton:disabled {{ color: {muted}; border-color: {border_l}; }}".format(
                text=theme.TEXT_PRIMARY, border=theme.BORDER,
                bg_h=theme.BG_HOVER, border_h=theme.BORDER_HOVER,
                muted=theme.TEXT_MUTED, border_l=theme.BORDER_LIGHT)
        )
        rollback.setCursor(Qt.PointingHandCursor)
        if is_installed:
            rollback.setEnabled(False)
        rollback.clicked.connect(lambda _=False, v=version: self._on_rollback(v))
        head.addWidget(rollback)

        rl.addLayout(head)

        notes = (info.get("changelog") or "").strip()
        if notes:
            note_label = QtWidgets.QLabel(notes)
            note_label.setWordWrap(True)
            note_label.setStyleSheet(
                "color: {}; font-size: 11px; background: transparent;"
                .format(theme.TEXT_SECONDARY)
            )
            rl.addWidget(note_label)
        else:
            empty = QtWidgets.QLabel(t("version_history_no_notes"))
            empty.setStyleSheet(
                "color: {}; font-size: 11px; background: transparent;"
                .format(theme.TEXT_MUTED)
            )
            rl.addWidget(empty)

        return row

    def _tag(self, text, color):
        """Pill badge — visual matches package_card.TypeBadge."""
        lbl = QtWidgets.QLabel(text)
        lbl.setFixedHeight(18)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
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
        return lbl

    def _on_rollback(self, version):
        reply = QtWidgets.QMessageBox.question(
            self, t("version_history_rollback"),
            t("version_history_confirm_rollback", version),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        self._chosen_version = version
        self.accept()

    def chosen_version(self):
        return self._chosen_version
