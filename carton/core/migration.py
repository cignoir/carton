"""Migrate a UUID-keyed registry to the namespace/name identity model.

Usage::

    python -m carton migrate-registry --registry path/to/registry.json --namespace mystudio

For each UUID-keyed package entry:

1. Compute new key ``"<namespace>/<name>"``.
2. Move ``packages/<uuid>/<version>/<name>-<version>.zip`` to
   ``packages/<namespace>/<name>/<version>/<name>-<version>.zip``.
3. Inside each zip, rewrite ``package.json``: drop ``id``, add ``namespace``.
4. Recompute sha256/size_bytes (zip contents change).
5. Update ``download_url``.
6. Rewrite ``registry.json`` with new keys + ``first_published_by`` /
   ``first_published_at``.
7. Rebuild ``icons.zip``.

Collisions (two UUIDs sharing the same ``name`` under one namespace) abort the
migration with a clear error.
"""

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone

from carton.core.identity import validate_namespace, validate_name


class MigrationError(RuntimeError):
    """Raised on any unrecoverable migration condition."""


def _is_uuid_key(key):
    """Heuristic: looks like a UUID v4 string (8-4-4-4-12 hex)."""
    if not isinstance(key, str) or len(key) != 36:
        return False
    parts = key.split("-")
    if len(parts) != 5:
        return False
    expected = (8, 4, 4, 4, 12)
    if tuple(len(p) for p in parts) != expected:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in key.replace("-", ""))


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _rewrite_zip_package_json(src_zip, dst_zip, namespace, name):
    """Extract ``src_zip``, rewrite its inner package.json, repack to ``dst_zip``."""
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(src_zip, "r") as zf:
            zf.extractall(tmp)

        pkg_json_path = os.path.join(tmp, "package.json")
        if os.path.exists(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                data = {}
        else:
            data = {}
        data.pop("id", None)
        data["namespace"] = namespace
        data["name"] = name
        with open(pkg_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        os.makedirs(os.path.dirname(dst_zip), exist_ok=True)
        with zipfile.ZipFile(dst_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(tmp):
                for fname in files:
                    full = os.path.join(root, fname)
                    arc = os.path.relpath(full, tmp)
                    zf.write(full, arc)


def _rebuild_icons_archive(registry_base):
    icons_dir = os.path.join(registry_base, "icons")
    if not os.path.isdir(icons_dir):
        return
    pngs = [f for f in os.listdir(icons_dir) if f.lower().endswith(".png")]
    if not pngs:
        return
    archive_path = os.path.join(registry_base, "icons.zip")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for png in pngs:
            zf.write(os.path.join(icons_dir, png), png)


def migrate_registry(registry_path, namespace, dry_run=False, log=print):
    """Migrate a single ``registry.json`` in place.

    Returns a dict summarizing the migration.
    """
    registry_path = os.path.normpath(registry_path)
    if not os.path.exists(registry_path):
        raise MigrationError("registry not found: {}".format(registry_path))

    namespace = validate_namespace(namespace)
    base_dir = os.path.dirname(registry_path)

    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    old_packages = registry.get("packages", {}) or {}
    if not old_packages:
        log("[migrate] nothing to migrate (empty registry)")
        return {"migrated": 0, "skipped": 0}

    # Plan: for each entry compute the new key. Detect collisions first.
    plans = []
    seen_keys = {}
    for old_key, pkg in old_packages.items():
        raw_name = pkg.get("name") or old_key
        try:
            name = validate_name(raw_name)
        except Exception as e:
            raise MigrationError("invalid name {!r} on entry {}: {}".format(raw_name, old_key, e))
        new_key = "{}/{}".format(namespace, name)
        if new_key in seen_keys:
            raise MigrationError(
                "collision: both UUID {} and {} would migrate to {}".format(
                    seen_keys[new_key], old_key, new_key)
            )
        seen_keys[new_key] = old_key
        plans.append((old_key, new_key, name, pkg))

    log("[migrate] {} package(s) will be migrated under namespace '{}'".format(len(plans), namespace))
    for old_key, new_key, _name, _pkg in plans:
        log("  {} -> {}".format(old_key, new_key))

    if dry_run:
        log("[migrate] dry run; no changes written")
        return {"migrated": 0, "skipped": len(plans), "dry_run": True}

    new_packages = {}
    migrated = 0

    for old_key, new_key, name, pkg in plans:
        new_pkg = dict(pkg)
        new_pkg["namespace"] = namespace
        new_pkg["name"] = name

        # first_published_*: derive from earliest version's released_at + author
        versions = pkg.get("versions", {}) or {}
        earliest = None
        for ver_info in versions.values():
            released = ver_info.get("released_at", "")
            if released and (earliest is None or released < earliest):
                earliest = released
        new_pkg.setdefault("first_published_by", pkg.get("author", ""))
        new_pkg.setdefault("first_published_at",
                           earliest or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

        new_versions = {}
        for ver_key, ver_info in versions.items():
            new_ver = dict(ver_info)
            old_zip = os.path.join(base_dir, "packages", old_key, ver_key,
                                   "{}-{}.zip".format(name, ver_key))
            if not os.path.exists(old_zip):
                # try alternate filename
                alt = pkg.get("name", name)
                old_zip = os.path.join(base_dir, "packages", old_key, ver_key,
                                       "{}-{}.zip".format(alt, ver_key))
            new_zip = os.path.join(base_dir, "packages", namespace, name, ver_key,
                                   "{}-{}.zip".format(name, ver_key))

            if os.path.exists(old_zip):
                _rewrite_zip_package_json(old_zip, new_zip, namespace, name)
                new_ver["sha256"] = _sha256_of(new_zip)
                new_ver["size_bytes"] = os.path.getsize(new_zip)
                new_ver["download_url"] = "packages/{}/{}/{}/{}-{}.zip".format(
                    namespace, name, ver_key, name, ver_key)
            else:
                log("[migrate] WARN: zip missing for {} v{}: {}".format(old_key, ver_key, old_zip))
                # Best effort: still update download_url to the expected new path
                new_ver["download_url"] = "packages/{}/{}/{}/{}-{}.zip".format(
                    namespace, name, ver_key, name, ver_key)

            new_versions[ver_key] = new_ver

        new_pkg["versions"] = new_versions
        new_packages[new_key] = new_pkg

        # Remove old packages/<uuid>/ directory
        old_dir = os.path.join(base_dir, "packages", old_key)
        if os.path.isdir(old_dir):
            shutil.rmtree(old_dir, ignore_errors=True)

        migrated += 1

    registry["schema_version"] = "3.0"
    registry["packages"] = new_packages
    registry["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    _rebuild_icons_archive(base_dir)

    log("[migrate] migrated {} package(s)".format(migrated))
    return {"migrated": migrated, "skipped": 0}
