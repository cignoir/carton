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
        self.setStyleSheet(theme.dialog_style())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(10)

        hint = QtWidgets.QLabel(t("version_history_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
        layout.addWidget(hint)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        container = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(container)
        col.setContentsMargins(0, 0, 4, 0)
        col.setSpacing(8)

        latest = pkg_data.get("latest_version", "")
        versions = pkg_data.get("versions", {}) or {}
        for ver in self._sorted_versions(versions.keys()):
            info = versions.get(ver, {}) or {}
            col.addWidget(self._make_row(ver, info, latest))
        col.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        close = QtWidgets.QPushButton(t("close"))
        close.setStyleSheet(theme.btn_ghost())
        close.clicked.connect(self.reject)
        btn_row.addWidget(close)
        layout.addLayout(btn_row)

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
        row = QtWidgets.QFrame()
        row.setStyleSheet(
            "QFrame {{ background: {bg}; border: 1px solid {border};"
            " border-radius: 6px; }}"
            .format(bg=theme.BG_SECONDARY, border=theme.BORDER)
        )
        rl = QtWidgets.QVBoxLayout(row)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(6)

        head = QtWidgets.QHBoxLayout()
        ver_label = QtWidgets.QLabel("v{}".format(version))
        ver_label.setStyleSheet(
            "font-weight: 700; font-size: 13px; color: {};".format(theme.TEXT_PRIMARY)
        )
        head.addWidget(ver_label)

        if version == latest:
            head.addWidget(self._tag(t("version_history_latest"), theme.ACCENT_GREEN))
        if version == self._installed_version:
            head.addWidget(self._tag(t("version_history_installed"), theme.ACCENT_BLUE))

        date = _format_date(info.get("released_at", ""))
        if date:
            d = QtWidgets.QLabel(date)
            d.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
            head.addWidget(d)

        head.addStretch(1)

        rollback = QtWidgets.QPushButton(t("version_history_rollback"))
        rollback.setStyleSheet(theme.btn_ghost_text())
        rollback.setCursor(Qt.PointingHandCursor)
        if version == self._installed_version:
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
                "color: {}; font-size: 11px; font-style: italic;"
                .format(theme.TEXT_MUTED)
            )
            rl.addWidget(empty)

        return row

    def _tag(self, text, color):
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(
            "font-size: 10px; font-weight: 600; color: {color};"
            " background: transparent; padding: 1px 6px;"
            " border: 1px solid {color}; border-radius: 3px;".format(color=color)
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
