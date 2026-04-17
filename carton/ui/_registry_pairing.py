"""Shared helpers for adding registries with UUID awareness.

Both the main window's "Publish → Add existing" flow and the Settings
Registries tab need the same logic: peek at the registry.json, offer to
stamp a missing ``registry_id``, and guard against duplicates already
known to the Config. This module centralises that so the two UI paths
can't drift apart.
"""

import json
import os

from carton.compat_urllib import urlopen, Request, URLError
from carton.core.registry_id import (
    read_registry_id,
    stamp_registry_id,
)

from carton.ui.compat import QtWidgets
from carton.ui.i18n import t


def read_local_registry_id(path):
    """Peek at a local registry.json and return its (id, data) tuple.

    Returns ``(id, data_dict)`` where ``id`` may be empty. Returns
    ``("", None)`` on read / parse failure — callers should surface the
    error to the user in their own context.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return "", None
    return read_registry_id(data), data


def probe_remote_registry_id(url, timeout=15):
    """One-off HTTP GET to a URL; return the registry_id it exposes.

    Any network / parse error yields ``""``. No retry, no caching — callers
    that need persistence should store the result on a RegistryEntry.
    """
    try:
        req = Request(url)
        req.add_header("Accept", "application/json")
        resp = urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, ValueError):
        return ""
    return read_registry_id(data)


def stamp_local_registry_with_prompt(parent, path, data):
    """Offer to write a fresh ``registry_id`` into a local registry.json.

    Returns the resulting id (empty if the user declined or the write
    failed). The file is only touched when the user accepts. Assumes
    ``data`` is the already-parsed JSON dict; the new id is written back
    by re-serialising the dict.
    """
    if data is None:
        return ""
    reply = QtWidgets.QMessageBox.question(
        parent, t("publish"), t("registry_stamp_prompt"),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
    )
    if reply != QtWidgets.QMessageBox.Yes:
        return ""
    rid, _ = stamp_registry_id(data)
    data.setdefault("schema_version", "3.1")
    # Preserve newer schema if the file was already 3.1+.
    if data.get("schema_version", "") in ("2.0", "3.0"):
        data["schema_version"] = "3.1"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError:
        return ""
    return rid


class DuplicateRegistryChoice:
    """Enum-like return value for ``resolve_duplicate_registry``."""
    CANCEL = "cancel"
    USE_EXISTING = "use_existing"
    ADD_ALIAS = "add_alias"


def resolve_duplicate_registry(parent, existing_entry):
    """Ask the user what to do when a registry is already known.

    ``existing_entry`` is the matched :class:`RegistryEntry`. Returns one
    of the :class:`DuplicateRegistryChoice` constants.
    """
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Question)
    box.setWindowTitle(t("registry_duplicate_title"))
    box.setText(t("registry_duplicate_msg", existing_entry.name, existing_entry.path))
    use_btn = box.addButton(
        t("registry_use_existing"), QtWidgets.QMessageBox.AcceptRole,
    )
    alias_btn = box.addButton(
        t("registry_add_alias"), QtWidgets.QMessageBox.AcceptRole,
    )
    box.addButton(t("cancel"), QtWidgets.QMessageBox.RejectRole)
    box.exec_()
    clicked = box.clickedButton()
    if clicked is use_btn:
        return DuplicateRegistryChoice.USE_EXISTING
    if clicked is alias_btn:
        return DuplicateRegistryChoice.ADD_ALIAS
    return DuplicateRegistryChoice.CANCEL


def normalize_registry_path(path):
    """Mirror ``RegistryEntry``'s path normalisation for comparisons."""
    if path.startswith(("http://", "https://")):
        return path
    return os.path.normpath(path)
