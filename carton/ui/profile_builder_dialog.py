"""Profile Builder dialog — author a distribution profile inside Carton.

Opens a separate workspace that operates on an in-memory
:class:`InstallerProfile`. None of the edits made here touch the live
``config.json``; the user explicitly chooses where to save the resulting
profile JSON via "Save as…", then feeds it into
``python -m carton build-installer --profile <path>`` to bake a custom
installer.

The actual editor widgets (language, proxy, auto-update, registries) are
the same components used by the Settings dialog — see
:mod:`carton.ui.settings_widgets`. The Profile Builder differs in that:

* its target is an :class:`InstallerProfile`, not a ``Config``
* the persist callback is a no-op (changes live in memory until Save as)
* language changes do not switch the live UI locale
* the proxy field does not push to ``os.environ``
* update-related buttons are hidden (probing GitHub from a profile makes
  no sense)
"""

import os

from carton.core.profile import InstallerProfile, InvalidProfileError
from carton.ui.compat import QtWidgets, Qt
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.settings_widgets import (
    AutoUpdateSection,
    LanguageSection,
    ProxySection,
    RegistriesSection,
)


class ProfileBuilderDialog(QtWidgets.QDialog):
    """Standalone editor for an InstallerProfile."""

    def __init__(self, current_config=None, parent=None):
        super().__init__(parent)
        self._current_config = current_config
        # Default starting state: a fresh blank profile. The user can
        # switch to "Copy current" / "Load from file…" via the dropdown.
        self._profile = InstallerProfile.blank()

        self.setWindowTitle(t("profile_builder_title"))
        self.setFixedSize(620, 720)
        self.setStyleSheet(theme.dialog_style() + theme.listwidget_style())

        self._setup_ui()

    def _setup_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(14)

        hint = QtWidgets.QLabel(t("profile_builder_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
        root.addWidget(hint)

        # Starting-state selector + Load button
        starter_row = QtWidgets.QHBoxLayout()
        starter_row.setSpacing(8)
        starter_label = QtWidgets.QLabel(t("profile_builder_starting_from") + ":")
        starter_label.setStyleSheet(theme.LABEL_DIM_BOLD)
        starter_row.addWidget(starter_label)

        self._starter_combo = QtWidgets.QComboBox()
        self._starter_combo.setStyleSheet(theme.combobox_style())
        self._starter_combo.addItem(t("profile_builder_start_blank"), "blank")
        if self._current_config is not None:
            self._starter_combo.addItem(t("profile_builder_start_current"), "current")
        self._starter_combo.addItem(t("profile_builder_start_load"), "load")
        self._starter_combo.currentIndexChanged.connect(self._on_starter_changed)
        starter_row.addWidget(self._starter_combo, stretch=1)
        root.addLayout(starter_row)

        # Sections — these get rebuilt whenever the target profile changes.
        self._sections_container = QtWidgets.QWidget()
        self._sections_layout = QtWidgets.QVBoxLayout(self._sections_container)
        self._sections_layout.setContentsMargins(0, 0, 0, 0)
        self._sections_layout.setSpacing(14)
        self._build_sections()
        root.addWidget(self._sections_container, stretch=1)

        # Footer buttons
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        save_btn = QtWidgets.QPushButton(t("profile_builder_save_as"))
        save_btn.setStyleSheet(theme.btn_primary())
        save_btn.clicked.connect(self._on_save_as)
        btn_row.addWidget(save_btn)
        close_btn = QtWidgets.QPushButton(t("profile_builder_close"))
        close_btn.setStyleSheet(theme.btn_ghost())
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ---- target lifecycle ----

    def _build_sections(self):
        """Rebuild every section against the current ``self._profile``.

        We blow the widgets away and recreate them whenever the target
        profile is replaced (Blank → Copy current → Load file). Simpler
        than wiring a generic "rebind target" path through every section.
        """
        # Clear out any existing children.
        while self._sections_layout.count():
            item = self._sections_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        noop = lambda: None  # nothing is persisted until "Save as…"
        self._sections_layout.addWidget(
            LanguageSection(self._profile, noop, apply_live=False)
        )
        self._sections_layout.addWidget(
            AutoUpdateSection(self._profile, noop, self_updater=None)
        )
        self._sections_layout.addWidget(
            ProxySection(self._profile, noop, apply_to_env=False)
        )
        self._sections_layout.addWidget(
            RegistriesSection(self._profile, noop)
        )

    # ---- starter dropdown ----

    def _on_starter_changed(self, index):
        choice = self._starter_combo.itemData(index)
        if choice == "blank":
            self._profile = InstallerProfile.blank()
            self._build_sections()
        elif choice == "current":
            if self._current_config is None:
                return
            self._profile = InstallerProfile.from_config(self._current_config)
            self._build_sections()
        elif choice == "load":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, t("profile_builder_load_dialog"), "",
                "Profile (*.json);;JSON (*.json)",
            )
            if not path:
                # Restore the dropdown so the user can pick a real option
                # next time without re-triggering the file picker.
                self._starter_combo.blockSignals(True)
                self._starter_combo.setCurrentIndex(0)
                self._starter_combo.blockSignals(False)
                return
            try:
                self._profile = InstallerProfile.load(path)
            except InvalidProfileError as e:
                QtWidgets.QMessageBox.warning(
                    self, t("profile_builder_load_error"), str(e),
                )
                self._starter_combo.blockSignals(True)
                self._starter_combo.setCurrentIndex(0)
                self._starter_combo.blockSignals(False)
                return
            self._build_sections()

    # ---- save ----

    def _on_save_as(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, t("profile_builder_save_dialog"),
            "carton-profile.json",
            "Profile (*.json);;JSON (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            self._profile.save(path)
        except OSError as e:
            QtWidgets.QMessageBox.warning(
                self, t("profile_builder_save_dialog"), str(e),
            )
            return
        QtWidgets.QMessageBox.information(
            self, t("profile_builder_save_dialog"),
            t("profile_builder_save_success", path),
        )
