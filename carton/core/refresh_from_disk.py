"""Re-read on-disk metadata for a registered My Tools package.

Carton stores a snapshot of ``package.json`` (or the ``.carton.json``
sidecar) into ``installed.json`` at registration time. After that, the
two diverge: the source manifest is the author's working copy, the
installed entry is what Carton's UI reads. This module gives the
EditDialog a way to *resync* — pull the latest values out of the
manifest so the user can review them and Save to update installed.json.

Carton's role stays "reader of package.json, never writer", so the
refresh flow only mutates installed.json. The author's source is
untouched.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

from carton.core.path_utils import resolve_local_path
from carton.core.sidecar import read_sidecar


# Fields lifted from a manifest into the form. We deliberately don't
# refresh ``namespace`` / ``name`` because changing those after
# registration would orphan installed.json's pkg_id keying — Carton's
# whole identity model assumes namespace/name are immutable post-Add.
REFRESHABLE_FIELDS = (
    "display_name",
    "version",
    "type",
    "icon",
    "homepage",
    "author",
    "description",
    "tags",
    "entry_point",
    "home_origin",
    "include_compiled",
)


class RefreshError(Exception):
    """Raised when the disk-side manifest can't be located or parsed.

    The message is user-facing — surface it directly in a message box.
    """


def read_manifest(local_path: str, is_folder: bool) -> Optional[Dict[str, Any]]:
    """Read the on-disk manifest for a registered local_path.

    Returns the parsed dict from ``package.json`` (folder packages) or
    the sidecar (single-file packages). Returns ``None`` if the path
    exists but no manifest is present — the EditDialog can decide
    whether that's an error worth surfacing.

    Raises :class:`RefreshError` if the path is missing, unreadable, or
    if the manifest is present but malformed (these are loud failures
    because the user explicitly asked for a refresh).
    """
    resolved = resolve_local_path(local_path)
    if not resolved or not os.path.exists(resolved):
        raise RefreshError(
            "Local path no longer exists: {}".format(local_path or "(unset)")
        )

    if is_folder or os.path.isdir(resolved):
        pkg_json = os.path.join(resolved, "package.json")
        if not os.path.exists(pkg_json):
            return None
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise RefreshError(
                "Couldn't read package.json: {}".format(e)
            ) from e
        if not isinstance(data, dict):
            raise RefreshError("package.json must be a JSON object.")
        return data

    # Single file: check for a ``.carton.json`` sidecar.
    sidecar = read_sidecar(resolved)
    if sidecar is None:
        return None
    if not isinstance(sidecar, dict):
        raise RefreshError("Sidecar must be a JSON object.")
    return sidecar


def diff_fields(
    current: Dict[str, Any], fresh: Dict[str, Any],
) -> Dict[str, Tuple[Any, Any]]:
    """Compare ``current`` (installed.json snapshot) against ``fresh``
    (just-read manifest). Returns ``{field: (old, new)}`` for every
    refreshable field whose value would change.

    Only :data:`REFRESHABLE_FIELDS` are considered. Unset values in the
    manifest are skipped — we never *erase* a field with a refresh.
    """
    changes: Dict[str, Tuple[Any, Any]] = {}
    for key in REFRESHABLE_FIELDS:
        if key not in fresh:
            continue
        new_val = fresh[key]
        old_val = current.get(key)
        if old_val != new_val:
            changes[key] = (old_val, new_val)
    return changes
