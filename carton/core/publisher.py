"""Publisher — write directly to a local registry."""

import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone


class Publisher:
    """Publish locally registered scripts to a registry.

    Creates a zip, places it in the registry directory, and updates registry.json.
    """

    def __init__(self, config):
        self._config = config

    def publish(self, pkg_data, pkg_id, registry_entry):
        """Publish to a registry.

        Args:
            pkg_data: Entry from installed.json
            pkg_id: Package UUID
            registry_entry: Target RegistryEntry to publish to

        Returns:
            dict with id, version
        """
        local_path = pkg_data.get("local_path", "")
        if not local_path or not os.path.exists(local_path):
            raise RuntimeError("File not found: {}".format(local_path))

        name = pkg_data.get("name", "")
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

        # 1. Create zip (temporarily in staging)
        zip_path = self._create_zip(
            local_path, name, version, is_folder,
            entry_point, display_name, icon, description, pkg_type, pkg_id, author,
        )

        sha256 = self._compute_sha256(zip_path)
        size_bytes = os.path.getsize(zip_path)

        # 2. Copy zip to registry directory
        registry_base = registry_entry.base_dir
        dest_dir = os.path.join(registry_base, "packages", pkg_id, version)
        os.makedirs(dest_dir, exist_ok=True)

        zip_name = "{}-{}.zip".format(name, version)
        dest_zip = os.path.join(dest_dir, zip_name)
        shutil.copy2(zip_path, dest_zip)

        # Delete staging zip
        try:
            os.remove(zip_path)
        except OSError:
            pass

        # 3. Update registry.json
        self._update_registry(
            registry_entry=registry_entry,
            pkg_id=pkg_id,
            name=name,
            display_name=display_name,
            version=version,
            pkg_type=pkg_type,
            description=description,
            icon=icon,
            author=author,
            sha256=sha256,
            size_bytes=size_bytes,
            entry_point=entry_point,
            tags=pkg_data.get("tags", []),
        )

        return {"id": pkg_id, "version": version}

    def _check_version_conflict(self, pkg_id, version, registry_entry):
        """Check if the same version has already been published."""
        reg_path = os.path.normpath(registry_entry.path)
        if not os.path.exists(reg_path):
            return
        with open(reg_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
        entry = registry.get("packages", {}).get(pkg_id)
        if entry and version in entry.get("versions", {}):
            raise RuntimeError(
                "v{} is already published. Increment the version before re-publishing.".format(version)
            )

    def _create_zip(self, local_path, name, version, is_folder,
                    entry_point, display_name, icon, description, pkg_type, pkg_id, author):
        """Create a zip file."""
        staging = self._config.staging_dir
        os.makedirs(staging, exist_ok=True)
        zip_path = os.path.join(staging, "{}-{}.zip".format(name, version))

        pkg_json = {
            "id": pkg_id,
            "name": name,
            "display_name": display_name,
            "version": version,
            "type": pkg_type,
            "description": description,
            "author": author,
            "maya_versions": ["2024", "2025", "2026", "2027"],
            "entry_point": entry_point,
            "icon": icon,
        }

        _EXCLUDE_DIRS = {"__pycache__", ".git", ".svn", ".hg", "tests", "test", "dist", "build", ".vscode", ".idea"}
        _EXCLUDE_FILES = {".gitignore", ".gitattributes", ".DS_Store", "Thumbs.db"}

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if is_folder:
                for root, dirs, files in os.walk(local_path):
                    dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
                    for f in files:
                        if f.endswith(".pyc") or f in _EXCLUDE_FILES:
                            continue
                        fp = os.path.join(root, f)
                        arcname = os.path.relpath(fp, local_path)
                        zf.write(fp, arcname)
                if "package.json" not in zf.namelist():
                    zf.writestr("package.json",
                                json.dumps(pkg_json, indent=2, ensure_ascii=False))
            else:
                zf.write(local_path, os.path.basename(local_path))
                zf.writestr("package.json",
                            json.dumps(pkg_json, indent=2, ensure_ascii=False))

        return zip_path

    def _update_registry(self, registry_entry, pkg_id, name, display_name,
                         version, pkg_type, description, icon, author,
                         sha256, size_bytes, entry_point, tags):
        """Update registry.json."""
        reg_path = os.path.normpath(registry_entry.path)

        if os.path.exists(reg_path):
            with open(reg_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
        else:
            registry = {"schema_version": "2.0", "packages": {}}

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if pkg_id not in registry["packages"]:
            registry["packages"][pkg_id] = {"versions": {}}

        entry = registry["packages"][pkg_id]
        entry["name"] = name
        entry["display_name"] = display_name
        entry["type"] = pkg_type
        entry["description"] = description
        entry["author"] = author
        entry["tags"] = tags
        entry["latest_version"] = version

        if icon:
            entry["icon"] = icon

        # download_url is a relative path
        rel_path = "packages/{}/{}/{}-{}.zip".format(pkg_id, version, name, version)
        entry["versions"][version] = {
            "maya_versions": ["2024", "2025", "2026", "2027"],
            "download_url": rel_path,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "released_at": now,
            "changelog": "",
        }

        registry["last_updated"] = now

        os.makedirs(os.path.dirname(reg_path), exist_ok=True)
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)

    def _compute_sha256(self, file_path):
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()
