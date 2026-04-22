"""Create / add-existing catalogue flows for the main window.

Both entry points live here because they are invoked from two places —
the user-driven "Add catalogue" sidebar action, and the mirror-pairing
fallback inside the publish flow — and duplicating the folder /
file-picker dance wasn't worth the coupling cost. These functions
mutate ``window._config`` directly and return the newly-registered
``CatalogueEntry`` (or ``None`` when cancelled).
"""

import json
import os

from carton.ui.compat import QtWidgets
from carton.ui.i18n import t


def create_new_catalogue(window, paired_remote=None):
    """Create a new empty v5.0 catalogue directory. Returns the CatalogueEntry or None.

    If ``paired_remote`` is given, the new catalogue inherits its
    ``catalogue_id`` so that publishes to the remote route here via
    :meth:`Config.find_local_mirror`. A pre-existing ``catalogue.json``
    / ``registry.json`` in the target folder is reused — if it has a
    mismatched id we rewrite to the remote's id (pairing intent).
    """
    folder = QtWidgets.QFileDialog.getExistingDirectory(
        window, t("setup_select_folder"),
    )
    if not folder:
        return None

    name, ok = QtWidgets.QInputDialog.getText(
        window, "Catalogue Name",
        t("setup_catalogue_name"),
        text=os.path.basename(folder),
    )
    if not ok or not name:
        return None

    from carton.core.migrations import (
        CATALOGUE_FILENAME,
        CATALOGUE_SCHEMA_VERSION,
        LEGACY_REGISTRY_FILENAME,
        migrate_local_registry_file_to_catalogue,
    )
    from carton.core.uuid_id import new_uuid, stamp_uuid
    from carton.ui._catalogue_pairing import probe_remote_catalogue_id

    cat_path = os.path.join(folder, CATALOGUE_FILENAME)
    legacy_path = os.path.join(folder, LEGACY_REGISTRY_FILENAME)

    # Decide the id to stamp — either inherit the remote's (pairing
    # intent) or mint a fresh one.
    if paired_remote is not None:
        rid = paired_remote.catalogue_id or probe_remote_catalogue_id(paired_remote.path)
        if rid:
            paired_remote.catalogue_id = rid
        else:
            rid = new_uuid()
            # Remote doesn't expose an id — the user will need to
            # re-upload this catalogue before the remote can resolve
            # back.
    else:
        rid = new_uuid()

    # A pre-existing legacy registry.json gets promoted to v5.0 first
    # so all subsequent reads land on catalogue.json. After migration
    # the file below is always cat_path.
    if not os.path.exists(cat_path) and os.path.exists(legacy_path):
        migrated = migrate_local_registry_file_to_catalogue(legacy_path)
        if migrated:
            cat_path = migrated

    if not os.path.exists(cat_path):
        # Fresh scaffold — v5.0 directly, skip the v3.1 detour that
        # only existed to be auto-migrated on next launch.
        os.makedirs(folder, exist_ok=True)
        with open(cat_path, "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": CATALOGUE_SCHEMA_VERSION,
                "catalogue_id": rid,
                "display_name": name,
                "packages": {},
            }, f, indent=2, ensure_ascii=False)
        os.makedirs(os.path.join(folder, "packages"), exist_ok=True)
    else:
        # Existing catalogue — stamp id if missing / mismatched. The
        # pairing case (rid from remote ≠ existing id) rewrites so
        # the mirror lookup works; otherwise just ensure an id exists.
        try:
            with open(cat_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {
                "schema_version": CATALOGUE_SCHEMA_VERSION,
                "packages": {},
            }
        data.setdefault("schema_version", CATALOGUE_SCHEMA_VERSION)
        current = (data.get("catalogue_id")
                   or data.get("registry_id") or "").strip().lower()
        if paired_remote is not None and rid and current != rid:
            data["catalogue_id"] = rid
        else:
            # Normal stamp path — read whatever id is there, top up
            # if missing. We funnel it through stamp_uuid via a
            # bridge dict so the same helper handles "preserve" and
            # "generate fresh" without duplicating the logic here.
            bridge = {"registry_id": current}
            stamp_uuid(bridge, "registry_id")
            rid = bridge["registry_id"]
            data["catalogue_id"] = rid
        # Drop the legacy key on rewrite so we don't keep a stale
        # duplicate — dual-emit is only appropriate at the Config
        # level, not inside catalogue.json itself (v5.0 schema
        # only defines catalogue_id).
        data.pop("registry_id", None)
        with open(cat_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    window._config.add_catalogue(name, cat_path, catalogue_id=rid)
    window._config.save()
    return window._config.catalogues[-1]


def add_existing_catalogue(window, paired_remote=None):
    """Browse for an existing catalogue.json (legacy registry.json also accepted). Returns the CatalogueEntry or None."""
    from carton.ui._catalogue_pairing import (
        DuplicateCatalogueChoice,
        find_duplicate_entry,
        read_local_catalogue_id,
        resolve_duplicate_catalogue,
        stamp_local_catalogue_with_prompt,
    )

    path = QtWidgets.QFileDialog.getOpenFileName(
        window, t("settings_select_catalogue"), "",
        "Catalogue (catalogue.json);;Legacy (registry.json);;JSON (*.json)",
    )[0]
    if not path:
        return None

    rid, data = read_local_catalogue_id(path)
    if not rid and data is not None:
        rid = stamp_local_catalogue_with_prompt(window, path, data)

    # Duplicate detection — skip the paired remote itself, because a
    # pairing flow is supposed to land on the same UUID (that's the
    # whole point). Also skip the same normalised path.
    existing = find_duplicate_entry(
        window._config.catalogues, rid, path,
        ignore=[paired_remote] if paired_remote is not None else None,
    )
    if existing is not None:
        choice = resolve_duplicate_catalogue(window, existing)
        if choice == DuplicateCatalogueChoice.CANCEL:
            return None
        if choice == DuplicateCatalogueChoice.USE_EXISTING:
            if paired_remote is not None and not paired_remote.catalogue_id:
                paired_remote.catalogue_id = rid
                window._config.save()
            return existing

    base = os.path.basename(os.path.dirname(path))
    name, ok = QtWidgets.QInputDialog.getText(
        window, "Catalogue Name",
        t("setup_catalogue_name"),
        text=base,
    )
    if not ok or not name:
        return None

    window._config.add_catalogue(name, path, catalogue_id=rid)
    if paired_remote is not None and rid and not paired_remote.catalogue_id:
        paired_remote.catalogue_id = rid
    window._config.save()
    return window._config.catalogues[-1]
