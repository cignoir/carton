"""Reusable settings sections.

Each section is a small QWidget that operates on a *target* object — either
a live :class:`carton.core.config.Config` or a
:class:`carton.core.profile.InstallerProfile`. Both expose the same
attribute shape (``language``, ``proxy``, ``auto_check_updates``,
``registries`` as a list of ``CatalogueEntry``, plus ``add_registry`` /
``remove_registry`` helpers), so the section code is identical regardless
of which one it edits.

The caller passes a ``persist`` callback that the section invokes after
every mutation. The Settings dialog passes ``config.save`` so changes
hit disk immediately; the Profile Builder passes a no-op so the
in-memory profile is mutated freely until the user clicks Save.
"""

import json
import os

from carton.compat_urllib import Request, urlopen
from carton.ui.compat import QtWidgets, Qt
from carton.ui import theme
from carton.ui.i18n import t


# ---------- input dialog helper -------------------------------------------


def wide_input(parent, title, label, text="", width=480):
    """Show a wider single-line input dialog. Returns ``(text, ok)``."""
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setFixedWidth(width)
    dialog.setStyleSheet(theme.dialog_style())
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(10)
    layout.addWidget(QtWidgets.QLabel(label))
    line = QtWidgets.QLineEdit(text)
    layout.addWidget(line)
    btn_layout = QtWidgets.QHBoxLayout()
    btn_layout.addStretch()
    ok_btn = QtWidgets.QPushButton("OK")
    ok_btn.setStyleSheet(theme.btn_primary())
    ok_btn.setDefault(True)
    ok_btn.clicked.connect(dialog.accept)
    btn_layout.addWidget(ok_btn)
    layout.addLayout(btn_layout)
    if dialog.exec_() == QtWidgets.QDialog.Accepted:
        return line.text(), True
    return "", False


# ---------- LanguageSection -----------------------------------------------


class LanguageSection(QtWidgets.QWidget):
    """Language picker bound to ``target.language``.

    Args:
        target: Object exposing ``language`` (str).
        persist: Callable invoked after the value changes.
        apply_live: When True, also calls i18n.set_language so subsequent
            t() calls reflect the choice. Off by default — only the live
            Settings dialog wants this; the Profile Builder doesn't.
    """

    def __init__(self, target, persist, apply_live=False, parent=None):
        super().__init__(parent)
        self._target = target
        self._persist = persist
        self._apply_live = apply_live

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        label = QtWidgets.QLabel(t("settings_language"))
        label.setStyleSheet(theme.LABEL_DIM_BOLD)
        layout.addWidget(label)

        self._combo = QtWidgets.QComboBox()
        self._combo.setStyleSheet(theme.combobox_style())
        self._combo.addItem(t("settings_language_auto"), "auto")
        self._combo.addItem("English", "en")
        self._combo.addItem("日本語", "ja")
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == self._target.language:
                self._combo.setCurrentIndex(i)
                break
        self._combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self._combo)

    def _on_changed(self, index):
        lang = self._combo.itemData(index)
        self._target.language = lang
        self._persist()
        if self._apply_live:
            from carton.ui.i18n import set_language, detect_language
            applied = detect_language() if lang == "auto" else lang
            set_language(applied)


# ---------- ProxySection ---------------------------------------------------


class ProxySection(QtWidgets.QWidget):
    """HTTP proxy line edit bound to ``target.proxy``.

    Args:
        target: Object exposing ``proxy`` (str).
        persist: Callable invoked after the value changes.
        apply_to_env: When True, also pushes the value into HTTP_PROXY /
            HTTPS_PROXY of the current process. Settings turns this on so
            urllib picks up the change immediately; Profile Builder leaves
            it off.
    """

    def __init__(self, target, persist, apply_to_env=False, parent=None):
        super().__init__(parent)
        self._target = target
        self._persist = persist
        self._apply_to_env = apply_to_env

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        label = QtWidgets.QLabel(t("settings_proxy"))
        label.setStyleSheet(theme.LABEL_DIM_BOLD)
        layout.addWidget(label)

        self._edit = QtWidgets.QLineEdit(self._target.proxy or "")
        self._edit.setPlaceholderText(t("settings_proxy_placeholder"))
        self._edit.setStyleSheet(
            "QLineEdit {{ background: {bg}; color: {text};"
            "  border: 1px solid {border}; border-radius: 4px; padding: 4px 6px; }}".format(
                bg=theme.BG_SECONDARY, text=theme.TEXT_PRIMARY, border=theme.BORDER)
        )
        self._edit.editingFinished.connect(self._on_changed)
        layout.addWidget(self._edit)

        hint = QtWidgets.QLabel(t("settings_proxy_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
        layout.addWidget(hint)

    def _on_changed(self):
        new_value = self._edit.text().strip()
        if new_value == (self._target.proxy or ""):
            return
        self._target.proxy = new_value
        self._persist()
        if self._apply_to_env:
            if not new_value:
                for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                    os.environ.pop(key, None)
            elif hasattr(self._target, "apply_proxy_to_env"):
                self._target.apply_proxy_to_env()


# ---------- AutoUpdateSection ---------------------------------------------


class AutoUpdateSection(QtWidgets.QWidget):
    """Checkbox bound to ``target.auto_check_updates``.

    Optionally hosts a "Check for updates now" button when a self_updater
    is provided. The button is hidden in the Profile Builder context
    (where probing GitHub from a profile makes no sense).
    """

    def __init__(self, target, persist, self_updater=None, parent=None):
        super().__init__(parent)
        self._target = target
        self._persist = persist
        self._self_updater = self_updater
        self._update_worker = None
        self._original_check_label = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._checkbox = QtWidgets.QCheckBox(t("settings_auto_update_check"))
        self._checkbox.setChecked(bool(self._target.auto_check_updates))
        self._checkbox.toggled.connect(self._on_toggled)
        layout.addWidget(self._checkbox)

        hint = QtWidgets.QLabel(t("settings_auto_update_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
        layout.addWidget(hint)

        if self._self_updater is not None:
            self._check_btn = QtWidgets.QPushButton(t("settings_check_update_now"))
            self._check_btn.setStyleSheet(theme.btn_ghost_text())
            self._check_btn.clicked.connect(self._on_check_now)
            layout.addWidget(self._check_btn, alignment=Qt.AlignLeft)
        else:
            self._check_btn = None

    def _on_toggled(self, checked):
        self._target.auto_check_updates = bool(checked)
        self._persist()

    def _on_check_now(self):
        if not self._self_updater:
            return
        if self._update_worker and self._update_worker.isRunning():
            return
        self._check_btn.setEnabled(False)
        self._original_check_label = self._check_btn.text()
        self._check_btn.setText(t("checking"))

        from carton.ui.main_window import _SelfUpdateCheckWorker
        self._update_worker = _SelfUpdateCheckWorker(self._self_updater, parent=self)
        self._update_worker.finished_signal.connect(self._on_check_done)
        self._update_worker.start()

    def _on_check_done(self, result, error):
        self._check_btn.setEnabled(True)
        if self._original_check_label:
            self._check_btn.setText(self._original_check_label)
        if error:
            QtWidgets.QMessageBox.warning(
                self, t("settings_auto_update_check"),
                t("settings_check_update_failed", error),
            )
            return
        if result:
            QtWidgets.QMessageBox.information(
                self, t("settings_auto_update_check"),
                t("settings_check_update_available", result[0]),
            )
        else:
            import carton
            QtWidgets.QMessageBox.information(
                self, t("settings_auto_update_check"),
                t("settings_check_update_uptodate", carton.__version__),
            )


# ---------- StrictVerifySection -------------------------------------------


class StrictVerifySection(QtWidgets.QWidget):
    """Checkbox bound to ``target.strict_verify``.

    Refuses installs whose registry entry has no sha256, closing the
    "remove the field to disable verification" hole. Off by default so
    legacy registries keep working until the user opts in.
    """

    def __init__(self, target, persist, parent=None):
        super().__init__(parent)
        self._target = target
        self._persist = persist

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._checkbox = QtWidgets.QCheckBox(t("settings_strict_verify"))
        self._checkbox.setChecked(bool(getattr(self._target, "strict_verify", False)))
        self._checkbox.toggled.connect(self._on_toggled)
        layout.addWidget(self._checkbox)

        hint = QtWidgets.QLabel(t("settings_strict_verify_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
        layout.addWidget(hint)

    def _on_toggled(self, checked):
        self._target.strict_verify = bool(checked)
        self._persist()


# ---------- RegistriesSection ---------------------------------------------


class RegistriesSection(QtWidgets.QWidget):
    """Registry list editor — list + add/edit/remove + reorder buttons.

    Operates on ``target.registries`` (list of CatalogueEntry) via the
    ``add_registry`` / ``remove_registry`` helpers both Config and
    InstallerProfile expose.
    """

    def __init__(self, target, persist, parent=None):
        super().__init__(parent)
        self._target = target
        self._persist = persist

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QtWidgets.QLabel(t("settings_registries"))
        label.setStyleSheet(theme.LABEL_DIM_BOLD)
        layout.addWidget(label)

        self._list = QtWidgets.QListWidget()
        for entry in self._target.registries:
            self._list.addItem(str(entry))
        self._list.itemDoubleClicked.connect(self._edit)
        layout.addWidget(self._list)

        btn_row = QtWidgets.QHBoxLayout()

        add_btn = QtWidgets.QPushButton(t("add"))
        add_btn.setStyleSheet(theme.btn_success())
        add_btn.clicked.connect(self._add)
        btn_row.addWidget(add_btn)

        edit_btn = QtWidgets.QPushButton(t("edit"))
        edit_btn.setStyleSheet(theme.btn_ghost_text())
        edit_btn.clicked.connect(self._edit)
        btn_row.addWidget(edit_btn)

        remove_btn = QtWidgets.QPushButton(t("remove"))
        remove_btn.setStyleSheet(theme.btn_danger())
        remove_btn.clicked.connect(self._remove)
        btn_row.addWidget(remove_btn)

        btn_row.addStretch()

        arrow_style = (
            "QPushButton {{ background: {bg}; color: {dim}; border: 1px solid {border};"
            "  border-radius: 4px; }}"
            "QPushButton:hover {{ color: {text}; }}"
        ).format(bg=theme.BG_SECONDARY, dim=theme.TEXT_DIM,
                 border=theme.BORDER, text=theme.TEXT_PRIMARY)

        up_btn = QtWidgets.QPushButton("▲")
        up_btn.setFixedWidth(32)
        up_btn.setStyleSheet(arrow_style)
        up_btn.clicked.connect(self._move_up)
        btn_row.addWidget(up_btn)

        down_btn = QtWidgets.QPushButton("▼")
        down_btn.setFixedWidth(32)
        down_btn.setStyleSheet(arrow_style)
        down_btn.clicked.connect(self._move_down)
        btn_row.addWidget(down_btn)

        layout.addLayout(btn_row)

    # ---- public ----------------------------------------------------------

    def reload_target(self, target):
        """Swap the underlying target and refresh the list view."""
        self._target = target
        self._refresh()

    # ---- private ---------------------------------------------------------

    def _refresh(self):
        self._list.clear()
        for entry in self._target.registries:
            self._list.addItem(str(entry))

    def _add(self):
        # Package-first order: single-package flows come first so the
        # common "just give me this tool" case lands fastest. Catalogue
        # flows (subscribing to / maintaining a multi-package index) stay
        # below but visible — catalogue is a useful aggregation feature,
        # not a hidden power-user thing.
        choices = [
            t("settings_add_github"),       # [0] single repo (probes pkg.json first)
            t("settings_add_package_url"),  # [1] single pkg.json URL
            t("settings_add_url"),          # [2] remote catalogue URL
            t("settings_add_local"),        # [3] local catalogue file
            t("settings_add_create_new"),   # [4] create new local catalogue
        ]
        chosen, ok = QtWidgets.QInputDialog.getItem(
            self, t("add"), t("settings_add_method"), choices, 0, False,
        )
        if not ok:
            return
        if chosen == choices[0]:
            self._add_github()
        elif chosen == choices[1]:
            self._add_package_url()
        elif chosen == choices[2]:
            self._add_remote()
        elif chosen == choices[3]:
            self._add_local()
        elif chosen == choices[4]:
            self._create_new_local()

    def _create_new_local(self):
        """Scaffold a fresh v5.0 catalogue in an empty folder.

        Pre-existing ``catalogue.json`` / ``registry.json`` in the picked
        folder are left alone — we just register the path and let
        :class:`CatalogueClient` read / auto-migrate them on first fetch.
        Only the "folder is empty" case creates a new file, and it's
        always v5.0 (no more v3.1 legacy scaffolds that would just get
        migrated on the next launch).
        """
        from carton.core.migrations import (
            CATALOGUE_FILENAME,
            CATALOGUE_SCHEMA_VERSION,
            LEGACY_REGISTRY_FILENAME,
        )
        from carton.core.registry_id import new_registry_id

        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, t("setup_select_folder"),
        )
        if not folder:
            return
        cat_path = os.path.join(folder, CATALOGUE_FILENAME)
        legacy_path = os.path.join(folder, LEGACY_REGISTRY_FILENAME)

        if os.path.exists(cat_path):
            self._finish_add(cat_path, os.path.basename(folder), catalogue_id="")
            return
        if os.path.exists(legacy_path):
            # CatalogueClient auto-migrates on first read; just register.
            self._finish_add(legacy_path, os.path.basename(folder), catalogue_id="")
            return

        try:
            rid = new_registry_id()
            os.makedirs(folder, exist_ok=True)
            with open(cat_path, "w", encoding="utf-8") as f:
                json.dump({
                    "schema_version": CATALOGUE_SCHEMA_VERSION,
                    "catalogue_id": rid,
                    "display_name": os.path.basename(folder),
                    "packages": {},
                }, f, indent=2, ensure_ascii=False)
            os.makedirs(os.path.join(folder, "packages"), exist_ok=True)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Carton", str(e))
            return
        self._finish_add(cat_path, os.path.basename(folder), catalogue_id=rid)

    def _add_local(self):
        from carton.ui._registry_pairing import (
            read_local_registry_id,
            stamp_local_registry_with_prompt,
        )

        path = QtWidgets.QFileDialog.getOpenFileName(
            self, t("settings_select_catalogue"), "",
            "Catalogue (catalogue.json);;Legacy (registry.json);;JSON (*.json)",
        )[0]
        if not path:
            return
        rid, data = read_local_registry_id(path)
        if not rid and data is not None:
            rid = stamp_local_registry_with_prompt(self, path, data)
        default_name = os.path.basename(os.path.dirname(path))
        self._finish_add(path, default_name, catalogue_id=rid)

    def _add_github(self):
        repo, ok = wide_input(self, "GitHub", t("settings_github_placeholder"))
        if not ok or not repo.strip():
            return
        repo = repo.strip().strip("/")
        if "/" not in repo or repo.count("/") != 1:
            QtWidgets.QMessageBox.warning(self, "Carton", t("settings_github_invalid"))
            return
        try:
            api_url = "https://api.github.com/repos/{}".format(repo)
            req = Request(api_url)
            req.add_header("Accept", "application/vnd.github.v3+json")
            resp = urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            branch = data.get("default_branch", "main")
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Carton", t("settings_github_error", str(e)),
            )
            return
        base = "https://raw.githubusercontent.com/{}/{}".format(repo, branch)
        # v5.0 single-package probe runs first: if the repo root carries a
        # ``package.json`` with a valid ``namespace/name``, treat it as a
        # single-package repo and register into the local personal
        # catalogue instead of walking the multi-package probe path. This
        # lets "paste owner/repo of your one tool" just work without the
        # user having to hand-author a catalogue.json.
        if self._try_register_single_package(base, repo):
            return
        # Probe order: v5.0 catalogue before v4.0 registry, nested
        # layout before root (preserves the existing habit of the
        # sample repos — the official template publishes under
        # ``registry/registry.json`` → now ``registry/catalogue.json``).
        candidates = [
            base + "/registry/catalogue.json",
            base + "/catalogue.json",
            base + "/registry/registry.json",
            base + "/registry.json",
        ]
        resolved = None
        for url in candidates:
            try:
                req = Request(url)
                resp = urlopen(req, timeout=10)
                if resp.getcode() == 200:
                    resolved = url
                    break
            except Exception:
                continue
        if not resolved:
            QtWidgets.QMessageBox.warning(
                self, "Carton", t("settings_github_no_catalogue", repo),
            )
            return
        from carton.ui._registry_pairing import probe_remote_registry_id
        rid = probe_remote_registry_id(resolved)
        self._finish_add(resolved, repo.split("/")[1], catalogue_id=rid)

    def _try_register_single_package(self, base, repo):
        """Probe ``{base}/package.json`` and register into personal catalogue.

        Returns True when the single-package path was taken (caller stops
        and skips the catalogue.json probe). False means either no
        ``package.json`` or the probed file lacked a usable
        ``namespace/name``; the caller continues to the catalogue probe.

        On a successful hit we mutate ``~/.carton/personal_catalogue.json``
        and surface a message box — we intentionally do NOT touch
        ``_target.registries`` because plan v5.0 keeps personal-catalogue
        entries separate from subscribed catalogues. The live UI list
        (``self._list``) only reflects subscribed catalogues, so nothing
        needs to change there.
        """
        from carton.core.personal_catalogue import PersonalCatalogue, derive_pkg_id
        from carton.ui._registry_pairing import probe_github_package_json

        pkg_data = probe_github_package_json(base)
        if pkg_data is None:
            return False
        pkg_id = derive_pkg_id(pkg_data)
        if not pkg_id:
            # package.json exists but lacks namespace/name — fall through
            # so the user still has a chance to hit a sibling
            # catalogue.json if the repo has both.
            return False

        catalogue = PersonalCatalogue.load()
        if catalogue.contains(pkg_id):
            QtWidgets.QMessageBox.information(
                self, "Carton",
                t("settings_github_pkg_already_added", pkg_id),
            )
            return True
        catalogue.add_github_package(pkg_id, repo)
        try:
            catalogue.save()
        except OSError as e:
            QtWidgets.QMessageBox.warning(
                self, "Carton", t("settings_github_error", str(e)),
            )
            return True
        QtWidgets.QMessageBox.information(
            self, "Carton",
            t("settings_github_pkg_registered", pkg_id),
        )
        return True

    def _add_package_url(self):
        """Register a single package by direct ``package.json`` URL.

        Counterpart to ``_add_github`` for repos that aren't on GitHub
        (or host their ``package.json`` at a non-standard path). Hits
        the URL, reads ``namespace``/``name`` from the returned JSON,
        and stores a ``url`` origin in the personal catalogue so the
        Library view can merge it in alongside subscribed catalogues.

        No ``_target.registries`` mutation — personal catalogue lives
        under ``~/.carton/`` and is machine-local (plan v5.0 spec).
        """
        from carton.core.personal_catalogue import (
            PersonalCatalogue, derive_pkg_id,
        )

        url, ok = wide_input(
            self, t("settings_add_package_url"),
            t("settings_package_url_placeholder"), width=560,
        )
        if not ok or not url.strip():
            return
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            QtWidgets.QMessageBox.warning(self, "Carton", t("settings_invalid_url"))
            return

        try:
            req = Request(url)
            req.add_header("Accept", "application/json")
            resp = urlopen(req, timeout=10)
            pkg_data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Carton",
                t("settings_package_url_error", str(e)),
            )
            return

        pkg_id = derive_pkg_id(pkg_data)
        if not pkg_id:
            QtWidgets.QMessageBox.warning(
                self, "Carton",
                t("settings_package_url_invalid_pkg"),
            )
            return

        catalogue = PersonalCatalogue.load()
        if catalogue.contains(pkg_id):
            QtWidgets.QMessageBox.information(
                self, "Carton",
                t("settings_github_pkg_already_added", pkg_id),
            )
            return
        catalogue.add_url_package(pkg_id, url)
        try:
            catalogue.save()
        except OSError as e:
            QtWidgets.QMessageBox.warning(
                self, "Carton", t("settings_github_error", str(e)),
            )
            return
        QtWidgets.QMessageBox.information(
            self, "Carton",
            t("settings_github_pkg_registered", pkg_id),
        )

    def _add_remote(self):
        from carton.ui._registry_pairing import probe_remote_registry_id

        url, ok = wide_input(
            self, t("settings_add_url"), t("settings_url_placeholder"), width=560,
        )
        if not ok or not url.strip():
            return
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            QtWidgets.QMessageBox.warning(self, "Carton", t("settings_invalid_url"))
            return
        parts = url.rstrip("/").rsplit("/", 2)
        default_name = parts[-2] if len(parts) >= 2 else "remote"
        if default_name in ("raw", "main", "master"):
            default_name = parts[-3] if len(parts) >= 3 else "remote"
        rid = probe_remote_registry_id(url)
        self._finish_add(url, default_name, catalogue_id=rid)

    def _finish_add(self, path, default_name="", catalogue_id=""):
        from carton.ui._registry_pairing import (
            DuplicateRegistryChoice,
            find_duplicate_entry,
            resolve_duplicate_registry,
        )

        # UUID-based duplicate detection: catches "same registry under a
        # different alias" before asking the user for a name. Falls back
        # silently when neither side has a catalogue_id — the legacy
        # name-based check below still guards.
        existing = find_duplicate_entry(
            self._target.registries, catalogue_id, path,
        )
        if existing is not None:
            choice = resolve_duplicate_registry(self, existing)
            if choice == DuplicateRegistryChoice.CANCEL:
                return
            if choice == DuplicateRegistryChoice.USE_EXISTING:
                return
            # ADD_ALIAS → fall through to the name prompt.

        name, ok = wide_input(
            self, "Catalogue Name", t("settings_catalogue_name"), text=default_name,
        )
        if not ok or not name:
            return
        for r in self._target.registries:
            if r.name == name:
                QtWidgets.QMessageBox.warning(
                    self, "Carton", t("settings_already_exists", name),
                )
                return
        self._target.add_registry(name, path, catalogue_id=catalogue_id)
        self._persist()
        self._list.addItem(str(self._target.registries[-1]))

    def _edit(self, item=None):
        row = self._list.currentRow()
        if row < 0:
            return
        entry = self._target.registries[row]

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(t("settings_edit_catalogue"))
        dialog.setFixedWidth(500)
        dialog.setStyleSheet(theme.dialog_style())
        dlg_layout = QtWidgets.QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(20, 20, 20, 20)
        dlg_layout.setSpacing(12)

        name_label = QtWidgets.QLabel(t("settings_catalogue_name"))
        name_label.setStyleSheet(theme.LABEL_DIM)
        dlg_layout.addWidget(name_label)
        name_input = QtWidgets.QLineEdit(entry.name)
        dlg_layout.addWidget(name_input)

        path_label = QtWidgets.QLabel(t("label_path"))
        path_label.setStyleSheet(theme.LABEL_DIM)
        dlg_layout.addWidget(path_label)
        path_input = QtWidgets.QLineEdit(entry.path)
        dlg_layout.addWidget(path_input)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QtWidgets.QPushButton(t("cancel"))
        cancel_btn.setStyleSheet(theme.btn_ghost())
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)
        save_btn = QtWidgets.QPushButton(t("save"))
        save_btn.setStyleSheet(theme.btn_primary())
        save_btn.clicked.connect(dialog.accept)
        save_btn.setDefault(True)
        btn_layout.addWidget(save_btn)
        dlg_layout.addLayout(btn_layout)

        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_name = name_input.text().strip()
            new_path = path_input.text().strip()
            if not new_name or not new_path:
                return
            from carton.core.config import CatalogueEntry
            self._target.registries[row] = CatalogueEntry(new_name, new_path)
            self._persist()
            self._refresh()
            self._list.setCurrentRow(row)

    def _remove(self):
        row = self._list.currentRow()
        if row < 0:
            return
        entry = self._target.registries[row]
        reply = QtWidgets.QMessageBox.question(
            self, "Remove Registry",
            t("settings_confirm_remove", entry.name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self._target.remove_registry(entry.name)
            self._persist()
            self._list.takeItem(row)

    def _move_up(self):
        row = self._list.currentRow()
        if row <= 0:
            return
        regs = self._target.registries
        regs[row], regs[row - 1] = regs[row - 1], regs[row]
        self._persist()
        self._refresh()
        self._list.setCurrentRow(row - 1)

    def _move_down(self):
        row = self._list.currentRow()
        if row < 0 or row >= len(self._target.registries) - 1:
            return
        regs = self._target.registries
        regs[row], regs[row + 1] = regs[row + 1], regs[row]
        self._persist()
        self._refresh()
        self._list.setCurrentRow(row + 1)
