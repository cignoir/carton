"""Publish confirmation dialog with optional release notes input."""

from carton.ui.compat import QtWidgets, Qt
from carton.ui.i18n import t
from carton.ui import theme


class PublishConfirmDialog(QtWidgets.QDialog):
    """Confirm a publish action and capture release notes for the version.

    Notes are stored under ``versions[ver].changelog`` in registry.json
    so consumers can browse the version history with context.
    """

    def __init__(self, display_name, version, registry_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("publish"))
        self.setMinimumWidth(480)
        self.setStyleSheet(theme.dialog_style())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)

        prompt = QtWidgets.QLabel(
            t("confirm_publish", display_name, version, registry_name)
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        notes_label = QtWidgets.QLabel(t("publish_release_notes_label"))
        notes_label.setStyleSheet(theme.LABEL_DIM)
        layout.addWidget(notes_label)

        self._notes = QtWidgets.QPlainTextEdit()
        self._notes.setPlaceholderText(t("publish_release_notes_placeholder"))
        self._notes.setFixedHeight(120)
        layout.addWidget(self._notes)

        self._embed_source_cb = QtWidgets.QCheckBox(t("publish_embed_source_path"))
        self._embed_source_cb.setChecked(True)
        self._embed_source_cb.setToolTip(t("publish_embed_source_path_tooltip"))
        layout.addWidget(self._embed_source_cb)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        cancel = QtWidgets.QPushButton(t("cancel"))
        cancel.setStyleSheet(theme.btn_ghost())
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        ok = QtWidgets.QPushButton(t("publish"))
        ok.setStyleSheet(theme.btn_primary())
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

    def release_notes(self):
        return self._notes.toPlainText().strip()

    def embed_source_path(self):
        return self._embed_source_cb.isChecked()
