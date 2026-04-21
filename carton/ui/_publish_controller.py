"""Publish / unpublish flow for the main window.

Extracted from ``main_window.py`` so every step of the publish state
machine — target picking, home-origin mismatch confirmation, namespace
prompting, the two publish modes (embedded catalogue / GitHub Release),
mirror pairing fallback, and the card-menu unpublish — sits in one
file. The controller holds a reference to the ``CartonWindow`` for
access to services (publisher / install_manager / config /
catalogue_client), the card layout, catalogue CRUD helpers, and
:meth:`refresh`. The internal ``_PublishTargetDialog`` lives here too
since it isn't used anywhere else.
"""

import json
import os

from carton.core.display_name_resolver import resolve_display_name
from carton.ui.compat import QtWidgets, Qt
from carton.ui.error_messages import show_error
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.package_card import PackageCard


class _PublishTargetDialog(QtWidgets.QDialog):
    """Dialog to choose a publish target catalogue.

    Accepts both local and remote entries. Remote rows annotate the mirror
    mapping so the user can see at a glance which local catalogue the
    remote will actually write to.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("publish"))
        self.setMinimumWidth(360)
        self._result_catalogue = None
        self._config = config

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        registries = list(config.catalogues)

        # Dropdown for existing registries (local + remote, annotated)
        if registries:
            label = QtWidgets.QLabel(t("publish_select_catalogue"))
            label.setStyleSheet("font-weight: 600;")
            layout.addWidget(label)

            self._combo = QtWidgets.QComboBox()
            for r in registries:
                label_text, tooltip = self._describe_target(r)
                self._combo.addItem(label_text, r)
                idx = self._combo.count() - 1
                if tooltip:
                    self._combo.setItemData(idx, tooltip, Qt.ToolTipRole)
            layout.addWidget(self._combo)

            select_btn = QtWidgets.QPushButton(t("publish"))
            select_btn.setStyleSheet(
                theme.btn_outline(theme.ACCENT_GREEN, theme.ACCENT_GREEN_HOVER)
            )
            select_btn.clicked.connect(self._on_select)
            layout.addWidget(select_btn)

            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.HLine)
            sep.setStyleSheet("color: {};".format(theme.BORDER_HOVER))
            layout.addWidget(sep)
        else:
            self._combo = None

        # v5.0 GitHub publish button — single-package flow that doesn't
        # need a catalogue. Sits above the catalogue-oriented buttons so
        # the package-first path is visually primary.
        gh_btn = QtWidgets.QPushButton(t("publish_to_github"))
        gh_btn.setStyleSheet(
            theme.btn_outline(theme.ACCENT_GREEN, theme.ACCENT_GREEN_HOVER)
        )
        gh_btn.clicked.connect(lambda: self.done(4))
        layout.addWidget(gh_btn)

        # Create new / Add existing buttons (catalogue flows)
        new_btn = QtWidgets.QPushButton(t("publish_create_catalogue"))
        new_btn.setStyleSheet(
            theme.btn_outline(theme.ACCENT_LINK, "#1d3040")
        )
        new_btn.clicked.connect(lambda: self.done(2))
        layout.addWidget(new_btn)

        add_btn = QtWidgets.QPushButton(t("publish_add_existing_catalogue"))
        add_btn.setStyleSheet(
            theme.btn_outline(theme.TEXT_SECONDARY, theme.BG_HOVER)
        )
        add_btn.clicked.connect(lambda: self.done(3))
        layout.addWidget(add_btn)

    def _on_select(self):
        if self._combo:
            self._result_catalogue = self._combo.currentData()
        self.accept()

    @property
    def selected_catalogue(self):
        return self._result_catalogue

    def _describe_target(self, entry):
        """Return ``(label, tooltip)`` for a catalogue row in the combo."""
        if not entry.is_remote:
            return entry.name, entry.path
        mirror = None
        if entry.catalogue_id:
            mirror = self._config.find_local_mirror(entry.catalogue_id)
        if mirror is not None:
            label = "{} → {}".format(entry.name, mirror.name)
            return label, t("publish_mirrors_to", mirror.name, mirror.path)
        label = "{}  ({})".format(entry.name, t("publish_no_mirror"))
        return label, t("publish_no_mirror_hint")


class PublishController:
    """Drives the publish / unpublish dialog flows for the main window."""

    def __init__(self, window):
        self._w = window

    # ---- main entry points ---------------------------------------------

    def start_publish(self, pkg_id):
        w = self._w
        if not w._publisher or not w._config:
            return

        pkg_data = w._install_manager.get_installed_packages().get(pkg_id)
        if not pkg_data:
            return

        target = self._pick_target(pkg_data)
        if target is None:
            return
        kind, payload = target

        namespace = self._ensure_namespace(pkg_id, pkg_data)
        if not namespace:
            return

        if kind == "embedded":
            target_catalogue = payload
            if not self._confirm_home_origin_mismatch(pkg_data, target_catalogue):
                return
            confirm_result = self._confirm_details(
                pkg_data, target_catalogue.name,
            )
            if not confirm_result:
                return
            release_notes, embed_source_path = confirm_result
            self._run_embedded(
                pkg_id, pkg_data, target_catalogue,
                namespace, release_notes, embed_source_path,
            )
        elif kind == "github":
            repo = payload
            confirm_result = self._confirm_details(pkg_data, repo)
            if not confirm_result:
                return
            release_notes, embed_source_path = confirm_result
            self._run_github(
                pkg_id, pkg_data, repo,
                namespace, release_notes, embed_source_path,
            )

    def on_card_unpublish(self, pkg_id, catalogue_name):
        """Handle the unpublish action triggered from a card badge menu."""
        w = self._w
        if not w._publisher or not w._config:
            return

        target = None
        for entry in w._config.catalogues:
            if entry.is_remote:
                continue
            if entry.name == catalogue_name:
                target = entry
                break
        if target is None:
            QtWidgets.QMessageBox.warning(
                w, t("unpublish_error"),
                "Registry '{}' not found.".format(catalogue_name),
            )
            return

        # Resolve display via the standard resolver: catalogue SoT for
        # catalogue-side entries, installed.json for My Tools.
        installed = w._install_manager.get_installed_packages() if w._install_manager else {}
        packages = w._catalogue_client.get_packages() if w._catalogue_client else {}
        display = resolve_display_name(
            pkg_id, installed.get(pkg_id), packages.get(pkg_id),
        )

        reply = QtWidgets.QMessageBox.question(
            w, t("unpublish"),
            t("confirm_unpublish", display, catalogue_name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        self.unpublish(pkg_id, target)

    def unpublish(self, pkg_id, catalogue_entry):
        w = self._w
        if not w._publisher:
            return

        installed = w._install_manager.get_installed_packages()
        pkg_data = installed.get(pkg_id, {})
        packages = w._catalogue_client.get_packages() if w._catalogue_client else {}
        display = resolve_display_name(pkg_id, pkg_data, packages.get(pkg_id))

        try:
            w._publisher.unpublish(pkg_id, catalogue_entry)

            # Demote double-bound entries to pure My Tools — the catalogue
            # bytes are gone but the user's local registration survives.
            w._install_manager.update_package_fields(
                pkg_id, {"source": "local"}
            )

            QtWidgets.QMessageBox.information(
                w, t("unpublish"),
                t("unpublish_success", display, catalogue_entry.name),
            )
            w.refresh()
        except Exception as e:
            show_error(w, e, operation="unpublish")

    # ---- helpers used by the window (cards / refresh) -------------------

    def build_published_map(self):
        """Return ``{pkg_id: [catalogue_name, ...]}`` for all writable local
        catalogues, built from a single pass over each catalogue.json.

        Remote registries are excluded: the user cannot unpublish from them,
        so there's no reason to surface the badge for those.
        """
        result = {}
        w = self._w
        if not w._config:
            return result
        for entry in w._config.catalogues:
            if entry.is_remote:
                continue
            reg_path = os.path.normpath(entry.path)
            if not os.path.exists(reg_path):
                continue
            try:
                with open(reg_path, "r", encoding="utf-8") as f:
                    catalogue_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            for pkg_id in catalogue_data.get("packages", {}).keys():
                result.setdefault(pkg_id, []).append(entry.name)
        return result

    def set_publish_button_state(self, pkg_id, busy=True):
        w = self._w
        for i in range(w._card_layout.count()):
            item = w._card_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, PackageCard) and widget._pkg_id == pkg_id:
                for btn in widget.findChildren(QtWidgets.QPushButton):
                    if btn.text() in (t("publish"), t("publishing")):
                        btn.setText(t("publishing") if busy else t("publish"))
                        btn.setEnabled(not busy)

    # ---- dialog steps ---------------------------------------------------

    def _pick_target(self, pkg_data):
        """Show the publish-target dialog. Returns ``(kind, payload)`` or None.

        * ``("embedded", CatalogueEntry)`` for catalogue publishes
        * ``("github", "owner/repo")`` for GitHub Release publishes

        Returns None when the user cancelled. The GitHub branch prompts
        for owner/repo and pre-fills from ``home_origin`` when available.
        """
        w = self._w
        dlg = _PublishTargetDialog(w._config, parent=w)
        result = dlg.exec_()
        if result == 1:  # Selected from dropdown
            entry = dlg.selected_catalogue
            return ("embedded", entry) if entry else None
        if result == 2:  # Create new
            entry = w._create_new_catalogue()
            return ("embedded", entry) if entry else None
        if result == 3:  # Add existing
            entry = w._add_existing_catalogue()
            return ("embedded", entry) if entry else None
        if result == 4:  # GitHub publish
            repo = self._prompt_github_repo(pkg_data)
            return ("github", repo) if repo else None
        return None

    def _prompt_github_repo(self, pkg_data):
        """Ask for owner/repo, pre-filled from home_origin when possible.

        Validates the ``owner/repo`` shape — returns the cleaned slug or
        ``""`` on cancel / invalid input.
        """
        w = self._w
        default_repo = ""
        home_origin = pkg_data.get("home_origin") or {}
        if home_origin.get("type") == "github":
            default_repo = home_origin.get("repo", "")
        repo, ok = QtWidgets.QInputDialog.getText(
            w, t("publish_to_github"),
            t("publish_github_prompt"),
            QtWidgets.QLineEdit.Normal, default_repo,
        )
        if not ok:
            return ""
        repo = repo.strip().strip("/")
        if "/" not in repo or repo.count("/") != 1:
            QtWidgets.QMessageBox.warning(
                w, t("publish"), t("settings_github_invalid"),
            )
            return ""
        return repo

    def _confirm_home_origin_mismatch(self, pkg_data, target_catalogue):
        """Warn if publishing to a different catalogue than the home one.

        Only meaningful for packages whose ``home_origin`` is an embedded
        catalogue — a github/url/local home has no comparable target at
        this call site, so we pass through without prompting. For embedded
        homes, compare by ``catalogue_id`` when both sides have one so a
        catalogue known under different names on different machines still
        passes without a prompt; fall back to name equality for entries
        that pre-date UUID stamping.

        Returns True to proceed, False if the user cancelled.
        """
        w = self._w
        home_origin = pkg_data.get("home_origin") or {}
        if home_origin.get("type") and home_origin.get("type") != "embedded":
            return True

        home_name = home_origin.get("catalogue_name", "")
        home_id = home_origin.get("catalogue_id", "")
        target_id = getattr(target_catalogue, "catalogue_id", "")

        if home_id and target_id:
            if home_id == target_id:
                return True
        elif home_name and home_name == target_catalogue.name:
            return True
        elif not home_name and not home_id:
            return True

        reply = QtWidgets.QMessageBox.question(
            w, t("publish"),
            t("publish_home_catalogue_mismatch",
              home_name or home_id, target_catalogue.name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        return reply == QtWidgets.QMessageBox.Yes

    def _ensure_namespace(self, pkg_id, pkg_data):
        """Return the package namespace, prompting and persisting if missing.

        Returns None if the user cancelled or supplied an invalid value.
        """
        w = self._w
        namespace = pkg_data.get("namespace", "")
        if namespace:
            return namespace
        from carton.core.identity import slugify_namespace
        ns, ok = QtWidgets.QInputDialog.getText(
            w, t("publish"), t("publish_namespace_prompt"),
        )
        if not ok or not ns.strip():
            return None
        namespace = slugify_namespace(ns)
        if not namespace:
            return None
        # Persist immediately so subsequent publishes don't re-ask
        w._install_manager.update_package_fields(
            pkg_id, {"namespace": namespace}
        )
        return namespace

    def _confirm_details(self, pkg_data, target_label):
        """Show the confirm dialog. Returns ``(release_notes, embed_source_path)``
        or None if cancelled.

        ``target_label`` is the human-readable target name — a catalogue
        name for embedded publishes, an ``owner/repo`` slug for GitHub
        publishes. It's only used in the prompt string so either works.
        """
        from carton.ui.publish_confirm_dialog import PublishConfirmDialog
        w = self._w
        display = pkg_data.get("display_name", "")
        local_version = pkg_data.get("version", "0.0.0")
        confirm = PublishConfirmDialog(
            display, local_version, target_label, parent=w,
        )
        if confirm.exec_() != QtWidgets.QDialog.Accepted:
            return None
        return confirm.release_notes(), confirm.embed_source_path()

    # ---- execution branches --------------------------------------------

    def _run_embedded(self, pkg_id, pkg_data, target_catalogue,
                      namespace, release_notes, embed_source_path):
        """Execute the publish call and reflect the result in installed.json."""
        from carton.core.publisher import RemoteMirrorMissingError

        w = self._w
        self.set_publish_button_state(pkg_id, busy=True)
        QtWidgets.QApplication.processEvents()

        try:
            result = w._publisher.publish(
                pkg_data, target_catalogue, namespace=namespace,
                release_notes=release_notes,
                embed_source_path=embed_source_path,
            )
        except RemoteMirrorMissingError as e:
            self.set_publish_button_state(pkg_id, busy=False)
            self._handle_missing_mirror(
                pkg_id, pkg_data, e, namespace,
                release_notes, embed_source_path,
            )
            return
        except Exception as e:
            self.set_publish_button_state(pkg_id, busy=False)
            self._show_publish_error(e)
            return

        # Re-key the installed entry under the canonical namespace/name.
        # The local path we actually wrote to may differ from the user's
        # selection (remote → mirror), so resolve the name via the result.
        written_name = result.get("published_via") or target_catalogue.name
        written_entry = self._find_catalogue_by_name(written_name) or target_catalogue
        fields = {
            "namespace": result["namespace"],
            "name": result["name"],
        }
        if not pkg_data.get("home_origin"):
            fields["home_origin"] = written_entry.to_home_origin_meta()
        w._install_manager.rekey_package(pkg_id, result["id"], fields)

        display = pkg_data.get("display_name", pkg_id)
        warnings = result.get("warnings") or []
        msg = t("publish_success", display)
        via = result.get("published_via")
        if via:
            msg += "\n\n" + t("publish_remote_sync_reminder", via)
        if warnings:
            msg += "\n\nWarnings:\n  - " + "\n  - ".join(warnings)
        QtWidgets.QMessageBox.information(w, t("publish"), msg)
        w.refresh()

    def _run_github(self, pkg_id, pkg_data, repo, namespace,
                    release_notes, embed_source_path):
        """Execute a GitHub Release publish and reflect the result.

        Unlike :meth:`_run_embedded`, there's no Config-level CatalogueEntry
        involved — the github origin is purely descriptive. On success we
        stamp ``home_origin = {"type":"github","repo":repo}`` into
        installed.json so a subsequent publish defaults to the same repo.
        """
        w = self._w
        self.set_publish_button_state(pkg_id, busy=True)
        QtWidgets.QApplication.processEvents()

        try:
            result = w._publisher.publish_github(
                pkg_data, repo,
                release_notes=release_notes,
                namespace=namespace,
                embed_source_path=embed_source_path,
            )
        except Exception as e:
            self.set_publish_button_state(pkg_id, busy=False)
            self._show_publish_error(e)
            return

        # Re-key the installed entry under the canonical namespace/name
        # and stamp home_origin so the next publish defaults to this repo.
        fields = {
            "namespace": result["namespace"],
            "name": result["name"],
        }
        if not pkg_data.get("home_origin"):
            fields["home_origin"] = {"type": "github", "repo": repo}
        w._install_manager.rekey_package(pkg_id, result["id"], fields)

        self._show_github_result(pkg_data, result)
        w.refresh()

    def _show_github_result(self, pkg_data, result):
        """Show the github publish outcome — release URL or manual steps."""
        w = self._w
        display = pkg_data.get("display_name", result.get("name", ""))
        warnings = result.get("warnings") or []
        manual_steps = result.get("manual_steps", "")
        release_url = result.get("release_url", "")

        if release_url and not manual_steps:
            msg = t("publish_github_success_url", display, release_url)
            if warnings:
                msg += "\n\nWarnings:\n  - " + "\n  - ".join(warnings)
            QtWidgets.QMessageBox.information(w, t("publish"), msg)
            return

        # Manual path: longer text, scrollable dialog so copy-paste works
        # cleanly. Built once so every manual-mode success / fallback goes
        # through the same surface.
        dlg = QtWidgets.QDialog(w)
        dlg.setWindowTitle(t("publish_github_manual_title"))
        dlg.setMinimumWidth(540)
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.setSpacing(10)
        intro = QtWidgets.QLabel(
            t("publish_github_manual_intro", display)
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        if warnings:
            warn_lbl = QtWidgets.QLabel(
                "Warnings:\n  - " + "\n  - ".join(warnings)
            )
            warn_lbl.setStyleSheet("color: {};".format(theme.ACCENT_ORANGE))
            warn_lbl.setWordWrap(True)
            layout.addWidget(warn_lbl)
        steps = QtWidgets.QPlainTextEdit()
        steps.setReadOnly(True)
        steps.setPlainText(manual_steps)
        steps.setMinimumHeight(240)
        layout.addWidget(steps)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        ok = QtWidgets.QPushButton(t("close"))
        ok.clicked.connect(dlg.accept)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)
        dlg.exec_()

    def _find_catalogue_by_name(self, name):
        for entry in self._w._config.catalogues:
            if entry.name == name:
                return entry
        return None

    def _handle_missing_mirror(self, pkg_id, pkg_data, err, namespace,
                               release_notes, embed_source_path):
        """Walk the user through pairing a local mirror with a remote entry.

        ``err.reason`` is one of ``"no_remote_id"`` / ``"no_local_mirror"``
        (see :class:`carton.core.publisher.RemoteMirrorMissingError`).
        """
        w = self._w
        remote = err.remote_entry
        if err.reason == "no_remote_id":
            QtWidgets.QMessageBox.warning(
                w, t("publish"),
                t("publish_no_remote_id", remote.name),
            )
            return

        box = QtWidgets.QMessageBox(w)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle(t("publish"))
        box.setText(t("publish_no_mirror_prompt", remote.name))
        create_btn = box.addButton(
            t("publish_create_mirror"), QtWidgets.QMessageBox.AcceptRole,
        )
        pair_btn = box.addButton(
            t("publish_pair_existing"), QtWidgets.QMessageBox.AcceptRole,
        )
        box.addButton(t("cancel"), QtWidgets.QMessageBox.RejectRole)
        box.exec_()
        clicked = box.clickedButton()

        mirror = None
        if clicked is create_btn:
            mirror = w._create_new_catalogue(paired_remote=remote)
        elif clicked is pair_btn:
            mirror = w._add_existing_catalogue(paired_remote=remote)

        if mirror is None:
            return
        # Retry publish against the original remote — the publisher will now
        # find the mirror via the shared catalogue_id.
        self._run_embedded(
            pkg_id, pkg_data, remote, namespace,
            release_notes, embed_source_path,
        )

    def _show_publish_error(self, exc):
        """Display a publish-error dialog mapped to a friendly message.

        VersionConflictError needs the version number formatted into its
        message, so it's handled inline here. Everything else flows through
        the central :func:`show_error` translator.
        """
        from carton.core.publisher import VersionConflictError
        w = self._w
        if isinstance(exc, VersionConflictError):
            QtWidgets.QMessageBox.warning(
                w, t("publish_error"),
                t("publish_already_published", exc.version),
            )
            return
        show_error(w, exc, operation="publish")
