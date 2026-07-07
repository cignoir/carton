"""Qt-side helpers for adding catalogues with UUID awareness.

Both the main window's "Publish → Add existing" flow and the Settings
Catalogues tab need the same logic: peek at the catalogue.json, offer
to stamp a missing ``catalogue_id``, and guard against duplicates
already known to the Config. The pure probe / comparison functions
live in :mod:`carton.core.catalogue.sources` (re-exported here so
existing call sites keep importing from one place); this module owns
only the pieces that put dialogs on screen.
"""

import json

# Re-exported for existing call sites — the implementations are Qt-free
# and live in core so the CLI / tests can use them too.
from carton.core.catalogue.sources import (  # noqa: F401
    find_duplicate_entry,
    normalize_catalogue_path,
    probe_github_package_json,
    probe_remote_catalogue_id,
    probe_remote_catalogue_meta,
    read_local_catalogue_id,
)
from carton.core.uuid_id import stamp_uuid

from carton.ui.compat import QtWidgets
from carton.ui.i18n import t


def stamp_local_catalogue_with_prompt(parent, path, data):
    """Offer to write a fresh ``catalogue_id`` into a local catalogue.json.

    Returns the resulting id (empty if the user declined or the write
    failed). The file is only touched when the user accepts. Assumes
    ``data`` is the already-parsed JSON dict; the new id is written back
    by re-serialising the dict.
    """
    if data is None:
        return ""
    reply = QtWidgets.QMessageBox.question(
        parent, t("publish"), t("catalogue_stamp_prompt"),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
    )
    if reply != QtWidgets.QMessageBox.Yes:
        return ""
    from carton.core.migrations import (
        CATALOGUE_SCHEMA_VERSION,
        migrate_registry_to_catalogue,
    )
    # Migrate to the current v5.0 shape so the stamp is paired with a
    # v5.0 write — leaving an old schema_version in place would re-
    # trigger migration on the next read for no benefit.
    data, _ = migrate_registry_to_catalogue(data)
    cid, _ = stamp_uuid(data, "catalogue_id")
    data["schema_version"] = CATALOGUE_SCHEMA_VERSION
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError:
        return ""
    return cid


class DuplicateCatalogueChoice:
    """Enum-like return value for ``resolve_duplicate_catalogue``."""
    CANCEL = "cancel"
    USE_EXISTING = "use_existing"
    ADD_ALIAS = "add_alias"


def resolve_duplicate_catalogue(parent, existing_entry):
    """Ask the user what to do when a catalogue is already known.

    ``existing_entry`` is the matched :class:`CatalogueEntry`. Returns one
    of the :class:`DuplicateCatalogueChoice` constants.
    """
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Question)
    box.setWindowTitle(t("catalogue_duplicate_title"))
    box.setText(t("catalogue_duplicate_msg", existing_entry.label, existing_entry.path))
    use_btn = box.addButton(
        t("catalogue_use_existing"), QtWidgets.QMessageBox.AcceptRole,
    )
    alias_btn = box.addButton(
        t("catalogue_add_alias"), QtWidgets.QMessageBox.AcceptRole,
    )
    box.addButton(t("cancel"), QtWidgets.QMessageBox.RejectRole)
    box.exec_()
    clicked = box.clickedButton()
    if clicked is use_btn:
        return DuplicateCatalogueChoice.USE_EXISTING
    if clicked is alias_btn:
        return DuplicateCatalogueChoice.ADD_ALIAS
    return DuplicateCatalogueChoice.CANCEL
