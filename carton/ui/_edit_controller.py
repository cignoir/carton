"""Edit flow for the main window.

Extracted from ``main_window.py`` for the same reason install / publish
were: the EditDialog round trip (dispatch on the dialog's action,
namespace-change validation, installed.json rekey) is a self-contained
state machine that shouldn't compete with sidebar / card code for
attention. The controller keeps a reference back to the
``CartonWindow`` — the window remains the source of truth for services
and view rebuilds, matching the other controllers.
"""

import os

from carton.core.identity import (
    InvalidIdentityError,
    slugify_namespace,
    validate_namespace,
)
from carton.core.path_utils import resolve_local_path, store_local_path
from carton.ui.compat import QtWidgets
from carton.ui.edit_dialog import EditDialog
from carton.ui.error_messages import show_error
from carton.ui.i18n import t


class EditController:
    """Drives the Edit dialog round trip for an installed package."""

    def __init__(self, window):
        self._w = window

    def show_edit(self, pkg_id):
        w = self._w
        pkg_data = w._install_manager.get_installed_packages().get(pkg_id, {})
        if not pkg_data:
            return

        # Check which catalogues have this package published
        published_regs = []
        if w._publisher:
            published_regs = w._publisher.find_published_catalogues(pkg_id)

        result = EditDialog.prompt(
            pkg_id, pkg_data,
            published_catalogues=published_regs, parent=w,
        )
        if not result:
            return

        action = result["action"]
        if action == "history":
            w._show_history_for(pkg_id)
        elif action == "unpublish":
            w._on_unpublish(pkg_id, result["catalogue"])
        elif action == "remove":
            if w._script_manager:
                w._script_manager.unregister(pkg_id)
            w._rebuild_sidebar()
            w._rebuild_cards()
        elif action == "save":
            self._apply_save(pkg_id, pkg_data, result, published_regs)

    def relink(self, pkg_id):
        """Point a My Tools entry at a source that moved.

        Registration holds a reference to the author's files instead of
        copying them, so moving or renaming the source leaves an entry
        that still has a card but can only fail on Launch — with an
        import error that never mentions the path. This is the repair:
        pick the new location, and the registration follows it.

        Only the path changes. Identity (namespace/name, and therefore
        the installed.json key and anything already published under it)
        is deliberately untouched — this is the same tool in a new
        place, not a new registration.
        """
        w = self._w
        pkg_data = w._install_manager.get_package(pkg_id)
        if not pkg_data:
            return

        old_path = resolve_local_path(pkg_data.get("local_path", ""))
        is_folder = pkg_data.get("is_folder", False)
        start_dir = os.path.dirname(old_path) if old_path else ""

        if is_folder:
            chosen = QtWidgets.QFileDialog.getExistingDirectory(
                w, t("relink_pick_folder"), start_dir,
            )
        else:
            chosen, _filter = QtWidgets.QFileDialog.getOpenFileName(
                w, t("relink_pick_file"), start_dir,
            )
        if not chosen:
            return

        chosen = os.path.normpath(chosen)
        if os.path.isdir(chosen) != bool(is_folder):
            # A folder package relinked to a single file (or the
            # reverse) would wire up the wrong env paths and fail at
            # launch in a way that looks like a different bug.
            QtWidgets.QMessageBox.warning(
                w, t("relink"),
                t("relink_wrong_kind_folder" if is_folder
                  else "relink_wrong_kind_file"),
            )
            return

        pkg_type = pkg_data.get("type", "")
        if w._script_manager:
            # Drop the stale env wiring before adding the new location,
            # so a relink doesn't leave the old path on sys.path for the
            # rest of the session.
            w._script_manager.rebind_local_path(
                pkg_id, chosen, old_path=old_path,
                pkg_type=pkg_type, is_folder=is_folder,
            )
        else:
            w._install_manager.update_package_fields(
                pkg_id, {"local_path": store_local_path(chosen)},
            )

        w._rebuild_sidebar()
        w._rebuild_cards()
        QtWidgets.QMessageBox.information(
            w, t("relink"), t("relink_done", chosen),
        )

    def _apply_save(self, pkg_id, pkg_data, result, published_regs):
        """Persist an EditDialog "save" result and refresh the views."""
        w = self._w
        fields = {
            "display_name": result["display_name"],
            "version": result["version"],
            "author": result["author"],
            "icon": result["icon"],
            "homepage": result["homepage"],
            "description": result["description"],
            "entry_point": result["entry_point"],
            "include_compiled": result.get("include_compiled", False),
        }

        new_pkg_id = self._resolve_namespace_change(
            pkg_id, pkg_data, result, published_regs, fields,
        )
        if new_pkg_id is None:
            return  # Validation failed; user already saw an error dialog

        if new_pkg_id != pkg_id:
            w._install_manager.rekey_package(pkg_id, new_pkg_id, fields)
        else:
            w._install_manager.update_package_fields(pkg_id, fields)
        # Sidebar counts and namespace children depend on the current
        # installed.json snapshot — refresh both views so renames /
        # namespace changes show up immediately.
        w._rebuild_sidebar()
        w._rebuild_cards()

    def _resolve_namespace_change(self, pkg_id, pkg_data, result,
                                  published_regs, fields):
        """Validate a namespace change from the edit dialog.

        Mutates ``fields`` in place to add ``namespace`` when the change is
        accepted. Returns the (possibly new) pkg_id, or None if validation
        failed (in which case an error dialog has already been shown).
        Namespace changes are ignored when the package is already published
        somewhere — the on-disk identity is locked.
        """
        new_ns = result.get("namespace", "")
        old_ns = pkg_data.get("namespace", "")
        if new_ns == old_ns or published_regs:
            return pkg_id

        # Slugify + validate; the dialog should already have shown a
        # preview but be defensive in case it didn't.
        if new_ns:
            new_ns = slugify_namespace(new_ns)
            try:
                new_ns = validate_namespace(new_ns)
            except InvalidIdentityError as e:
                show_error(self._w, e, operation="register")
                return None

        fields["namespace"] = new_ns
        name = pkg_data.get("name", "")
        return "{}/{}".format(new_ns, name) if new_ns else name
