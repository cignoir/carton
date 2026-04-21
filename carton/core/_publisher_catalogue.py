"""Catalogue-update helper for the publisher.

Writes a new package version into ``catalogue.json``. Lives outside
:class:`~carton.core.publisher.Publisher` because its only real
dependency on the publisher instance was ``_config`` — which was never
actually touched. The inputs are data, the outputs are a mutated
catalogue file on disk and a warnings list (author mismatch, etc.).
"""

import json
import os
from datetime import datetime, timezone

from carton.core.catalogue_icons import (
    normalise_icon_for_storage,
    rebuild_icons_archive,
)
from carton.core.migrations import (
    CATALOGUE_SCHEMA_VERSION,
    migrate_registry_to_catalogue,
)
from carton.core.uuid_id import stamp_uuid


_DEFAULT_MAYA_VERSIONS = ["2024", "2025", "2026", "2027"]


def update_catalogue(catalogue_path, catalogue_entry, pkg_id,
                     namespace, name, display_name, version, pkg_type,
                     description, icon, author, sha256, size_bytes,
                     entry_point, maya_versions, tags, release_notes=""):
    """Update catalogue.json in place. Returns a list of warning strings.

    Mutates ``catalogue_entry.catalogue_id`` (stamps the catalogue's
    UUID back onto the Config-level entry so the next publish to the
    same entry already knows the id). Rebuilds ``icons.zip`` next to
    the catalogue on success.
    """
    out_path = os.path.normpath(catalogue_path)

    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            catalogue = json.load(f)
        # In-memory upgrade of any lingering v4.0 registry shape so the
        # rest of this function only has to think about v5.0.
        catalogue, _ = migrate_registry_to_catalogue(catalogue)
    else:
        catalogue = {
            "schema_version": CATALOGUE_SCHEMA_VERSION,
            "catalogue_id": "",
            "packages": {},
        }

    catalogue["schema_version"] = CATALOGUE_SCHEMA_VERSION
    catalogue_id, _ = stamp_uuid(catalogue, "catalogue_id")
    catalogue_entry.catalogue_id = catalogue_id

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    warnings = []

    packages = catalogue.setdefault("packages", {})
    if pkg_id not in packages:
        packages[pkg_id] = {
            "origin": {"type": "embedded", "versions": {}},
            "first_published_by": author,
            "first_published_at": now,
        }

    entry = packages[pkg_id]
    # Ensure origin is present and of the embedded type. A pkg_id that
    # previously lived as a non-embedded origin in this catalogue is
    # a configuration error — we'd silently break consumers if we
    # let it slide, so reset to embedded.
    origin = entry.get("origin")
    if not isinstance(origin, dict) or origin.get("type") != "embedded":
        origin = {"type": "embedded", "versions": {}}
        entry["origin"] = origin

    # Author mismatch warning (don't block — just inform)
    first_author = entry.get("first_published_by", "")
    if first_author and author and first_author != author:
        warnings.append(
            "author '{}' is publishing a package first published by '{}'".format(
                author, first_author)
        )
    entry.setdefault("first_published_by", author)
    entry.setdefault("first_published_at", now)

    entry["namespace"] = namespace
    entry["name"] = name
    entry["display_name"] = display_name
    entry["type"] = pkg_type
    entry["description"] = description
    entry["author"] = author
    entry["tags"] = tags
    # Mirror entry_point as a preview hint so the card UI can show
    # Launch / Activate without installing first. The inner zip's
    # package.json remains the runtime SoT.
    if entry_point:
        entry["entry_point"] = entry_point

    normalised_icon = normalise_icon_for_storage(icon)
    if normalised_icon is not None and normalised_icon != "":
        entry["icon"] = normalised_icon
    else:
        entry.pop("icon", None)

    rel_path = "packages/{}/{}/{}/{}-{}.zip".format(namespace, name, version, name, version)
    versions = origin.setdefault("versions", {})
    versions[version] = {
        "maya_versions": list(maya_versions) if maya_versions else list(_DEFAULT_MAYA_VERSIONS),
        "download_url": rel_path,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "released_at": now,
        "changelog": release_notes or "",
    }
    origin["latest_version"] = version

    catalogue["last_updated"] = now

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(catalogue, f, indent=2, ensure_ascii=False)

    rebuild_icons_archive(catalogue_entry.base_dir)
    return warnings
