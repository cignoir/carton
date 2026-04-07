"""Publisher — write directly to a local registry.

Identity model: each package is keyed by ``"<namespace>/<name>"``. Both must be
set; raise :class:`MissingNamespaceError` if not. The first publish records
``first_published_by`` / ``first_published_at`` on the registry entry; later
publishes by a different author trigger a warning (returned in the result dict)
but are not blocked.
"""

import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone

from carton.core.identity import (
    InvalidIdentityError,
    make_pkg_id,
    validate_namespace,
    validate_name,
)
from carton.core.path_utils import resolve_local_path
from carton.core.sidecar import write_sidecar, read_sidecar


class VersionConflictError(RuntimeError):
    """Raised when attempting to publish a version that already exists."""

    def __init__(self, version):
        self.version = version
        super().__init__(version)


class MissingNamespaceError(RuntimeError):
    """Raised when a publish is attempted without a namespace."""


class Publisher:
    """Publish locally registered scripts to a registry."""

    def __init__(self, config):
        self._config = config

    def publish(self, pkg_data, registry_entry, namespace=None, release_notes=""):
        """Publish to a registry.

        Args:
            pkg_data: Entry from installed.json. May or may not already carry
                a ``namespace`` field.
            registry_entry: Target RegistryEntry to publish to (must be local).
            namespace: Optional override; if given, takes precedence over
                ``pkg_data['namespace']``. Required if neither is set.

        Returns:
            dict with ``id``, ``namespace``, ``name``, ``version`` and an
            optional ``warnings`` list (e.g. author mismatch).
        """
        if registry_entry.is_remote:
            raise RuntimeError("Cannot publish to a remote registry: {}".format(registry_entry.name))

        # Stored local_path may be a portable form like ``~/tools/foo.py``;
        # expand before touching the filesystem.
        local_path = resolve_local_path(pkg_data.get("local_path", ""))
        if not local_path or not os.path.exists(local_path):
            raise RuntimeError("File not found: {}".format(local_path))

        ns_raw = namespace or pkg_data.get("namespace", "")
        if not ns_raw:
            raise MissingNamespaceError(
                "namespace is required to publish; set it in package.json / "
                "sidecar, or pass via the Add dialog."
            )
        try:
            ns = validate_namespace(ns_raw)
            name = validate_name(pkg_data.get("name", ""))
        except InvalidIdentityError as e:
            raise MissingNamespaceError(str(e))

        pkg_id = make_pkg_id(ns, name)

        display_name = pkg_data.get("display_name", name)
        version = pkg_data.get("version", "0.1.0")
        pkg_type = pkg_data.get("type", "python_package")
        icon = pkg_data.get("icon", "")
        description = pkg_data.get("description", "")
        entry_point = pkg_data.get("entry_point", {})
        is_folder = pkg_data.get("is_folder", False)
        author = pkg_data.get("author", "")

        # Check for same version conflict
        self._check_version_conflict(pkg_id, version, registry_entry)

        # 1. Create zip (in staging)
        zip_path = self._create_zip(
            local_path, ns, name, version, is_folder,
            entry_point, display_name, icon, description, pkg_type, author,
            home_registry=pkg_data.get("home_registry"),
        )

        sha256 = self._compute_sha256(zip_path)
        size_bytes = os.path.getsize(zip_path)

        # 2. Copy zip to registry directory: packages/<namespace>/<name>/<version>/
        registry_base = registry_entry.base_dir
        dest_dir = os.path.join(registry_base, "packages", ns, name, version)
        os.makedirs(dest_dir, exist_ok=True)

        zip_name = "{}-{}.zip".format(name, version)
        dest_zip = os.path.join(dest_dir, zip_name)
        shutil.copy2(zip_path, dest_zip)

        try:
            os.remove(zip_path)
        except OSError:
            pass

        # 3. Copy icon file to registry icons/ directory.
        # Preserve the original filename so consumers can fetch it verbatim.
        registry_icon = icon
        if self._is_icon_file(icon):
            icon_basename = os.path.basename(icon)
            self._copy_icon_to_registry(icon, icon_basename, registry_base)
            registry_icon = icon_basename

        # 4. Update registry.json + rebuild icons.zip
        warnings = self._update_registry(
            registry_entry=registry_entry,
            pkg_id=pkg_id,
            namespace=ns,
            name=name,
            display_name=display_name,
            version=version,
            pkg_type=pkg_type,
            description=description,
            icon=registry_icon,
            author=author,
            sha256=sha256,
            size_bytes=size_bytes,
            entry_point=entry_point,
            tags=pkg_data.get("tags", []),
            release_notes=release_notes,
        )

        # 5. Persist namespace/name back into source so the next user converges
        self._persist_identity_to_source(
            local_path, ns, name, is_folder,
            home_registry=pkg_data.get("home_registry") or {"name": registry_entry.name},
        )

        result = {"id": pkg_id, "namespace": ns, "name": name, "version": version}
        if warnings:
            result["warnings"] = warnings
        return result

    def _check_version_conflict(self, pkg_id, version, registry_entry):
        """Check if the same version has already been published."""
        reg_path = os.path.normpath(registry_entry.path)
        if not os.path.exists(reg_path):
            return
        with open(reg_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
        entry = registry.get("packages", {}).get(pkg_id)
        if entry and version in entry.get("versions", {}):
            raise VersionConflictError(version)

    def _create_zip(self, local_path, namespace, name, version, is_folder,
                    entry_point, display_name, icon, description, pkg_type, author,
                    home_registry=None):
        """Create a zip file in the staging directory."""
        staging = self._config.staging_dir
        os.makedirs(staging, exist_ok=True)
        zip_path = os.path.join(staging, "{}-{}.zip".format(name, version))

        pkg_json = {
            "namespace": namespace,
            "name": name,
            "display_name": display_name,
            "version": version,
            "type": pkg_type,
            "description": description,
            "author": author,
            "maya_versions": ["2024", "2025", "2026", "2027"],
            "entry_point": entry_point,
            "icon": os.path.basename(icon) if self._is_icon_file(icon) else icon,
        }
        if home_registry:
            pkg_json["home_registry"] = home_registry

        _EXCLUDE_DIRS = {"__pycache__", ".git", ".svn", ".hg", "tests", "test", "dist", "build", ".vscode", ".idea"}
        _EXCLUDE_FILES = {".gitignore", ".gitattributes", ".DS_Store", "Thumbs.db"}

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if is_folder:
                for root, dirs, files in os.walk(local_path):
                    dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
                    for f in files:
                        if f.endswith(".pyc") or f in _EXCLUDE_FILES:
                            continue
                        # Skip stale package.json — we'll inject the canonical one
                        if f == "package.json" and root == local_path:
                            continue
                        fp = os.path.join(root, f)
                        arcname = os.path.relpath(fp, local_path)
                        zf.write(fp, arcname)
                zf.writestr("package.json",
                            json.dumps(pkg_json, indent=2, ensure_ascii=False))
            else:
                zf.write(local_path, os.path.basename(local_path))
                zf.writestr("package.json",
                            json.dumps(pkg_json, indent=2, ensure_ascii=False))

        return zip_path

    def _update_registry(self, registry_entry, pkg_id, namespace, name, display_name,
                         version, pkg_type, description, icon, author,
                         sha256, size_bytes, entry_point, tags, release_notes=""):
        """Update registry.json. Returns a list of warning strings (may be empty)."""
        reg_path = os.path.normpath(registry_entry.path)

        if os.path.exists(reg_path):
            with open(reg_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
        else:
            registry = {"schema_version": "3.0", "packages": {}}

        # Auto-upgrade older schema_version on touch
        registry["schema_version"] = "3.0"

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        warnings = []

        if pkg_id not in registry["packages"]:
            registry["packages"][pkg_id] = {
                "versions": {},
                "first_published_by": author,
                "first_published_at": now,
            }

        entry = registry["packages"][pkg_id]
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
        entry["latest_version"] = version
        # Carry entry_point at the registry level so the card UI can decide
        # between Launch / Activate without having to install the package
        # first. The inner zip's package.json is still the source of truth at
        # install time.
        if entry_point:
            entry["entry_point"] = entry_point

        if icon:
            entry["icon"] = icon

        rel_path = "packages/{}/{}/{}/{}-{}.zip".format(namespace, name, version, name, version)
        entry["versions"][version] = {
            "maya_versions": ["2024", "2025", "2026", "2027"],
            "download_url": rel_path,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "released_at": now,
            "changelog": release_notes or "",
        }

        registry["last_updated"] = now

        os.makedirs(os.path.dirname(reg_path), exist_ok=True)
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)

        self._rebuild_icons_archive(registry_entry.base_dir)
        return warnings

    def _persist_identity_to_source(self, local_path, namespace, name, is_folder,
                                    home_registry=None):
        """Write namespace/name back into source so other clones converge.

        Folder packages: update or create ``<folder>/package.json``.
        Single files: create or update ``<file>.carton.json`` sidecar.
        """
        updates = {"namespace": namespace, "name": name}
        if home_registry:
            updates["home_registry"] = home_registry

        if is_folder:
            pkg_json_path = os.path.join(local_path, "package.json")
            data = {}
            if os.path.exists(pkg_json_path):
                try:
                    with open(pkg_json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    data = {}
            # Drop legacy id field if present
            data.pop("id", None)
            data.update(updates)
            with open(pkg_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            existing = read_sidecar(local_path) or {}
            existing.update(updates)
            write_sidecar(local_path, existing)

    def unpublish(self, pkg_id, registry_entry):
        """Remove a package from a registry.

        ``pkg_id`` is the canonical ``"<namespace>/<name>"``.
        """
        if registry_entry.is_remote:
            raise RuntimeError("Cannot unpublish from a remote registry: {}".format(registry_entry.name))

        reg_path = os.path.normpath(registry_entry.path)
        if not os.path.exists(reg_path):
            raise RuntimeError("Registry not found: {}".format(reg_path))

        with open(reg_path, "r", encoding="utf-8") as f:
            registry = json.load(f)

        packages = registry.get("packages", {})
        if pkg_id not in packages:
            raise RuntimeError("Package not found in registry: {}".format(pkg_id))

        entry = packages[pkg_id]
        namespace = entry.get("namespace", "")
        name = entry.get("name", pkg_id)

        # Delete the package directory tree
        if namespace and name:
            pkg_dir = os.path.join(registry_entry.base_dir, "packages", namespace, name)
        else:
            pkg_dir = os.path.join(registry_entry.base_dir, "packages", pkg_id)
        if os.path.isdir(pkg_dir):
            shutil.rmtree(pkg_dir)
            # Best-effort cleanup of empty namespace dir
            ns_dir = os.path.dirname(pkg_dir)
            try:
                if not os.listdir(ns_dir):
                    os.rmdir(ns_dir)
            except OSError:
                pass

        del packages[pkg_id]
        registry["last_updated"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)

        return {"id": pkg_id, "name": name}

    def find_published_registries(self, pkg_id):
        """Find all local registries that contain a given package id."""
        results = []
        for entry in self._config.registries:
            if entry.is_remote:
                continue
            reg_path = os.path.normpath(entry.path)
            if not os.path.exists(reg_path):
                continue
            try:
                with open(reg_path, "r", encoding="utf-8") as f:
                    registry = json.load(f)
                if pkg_id in registry.get("packages", {}):
                    results.append(entry)
            except (json.JSONDecodeError, OSError):
                continue
        return results

    @staticmethod
    def _is_icon_file(icon):
        """Return True if icon value is an existing image file path."""
        return (isinstance(icon, str)
                and icon.endswith((".png", ".jpg", ".svg"))
                and os.path.isabs(icon)
                and os.path.exists(icon))

    @staticmethod
    def _copy_icon_to_registry(icon_path, dest_filename, registry_base):
        """Copy an icon file to the registry's ``icons/`` directory verbatim.

        ``dest_filename`` is the basename to use in the registry; passing the
        original basename keeps the author's filename instead of forcing
        ``<name>.png``.
        """
        icons_dir = os.path.join(registry_base, "icons")
        os.makedirs(icons_dir, exist_ok=True)
        dest = os.path.join(icons_dir, dest_filename)
        shutil.copy2(icon_path, dest)

    def _rebuild_icons_archive(self, registry_base):
        """Rebuild icons.zip from all PNGs in the icons/ directory."""
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

    def _compute_sha256(self, file_path):
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()
