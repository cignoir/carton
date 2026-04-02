"""InstallManager — manages package install, uninstall, and activation."""

import json
import os
import zipfile
from datetime import datetime, timezone

from carton.core.handlers import get_handler
from carton.models.package_info import PackageInfo


class InstallManager:
    """Facade for package management using Handlers.

    Keys in installed.json are UUIDs (pkg_id).
    Directory names use the name (import name).
    """

    def __init__(self, config, env_manager):
        self._config = config
        self._env_manager = env_manager
        self._installed = self._load_installed()

    def _load_installed(self):
        """Load installed.json."""
        path = self._config.installed_json_path
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("schema_version") == "1.0":
                data = self._migrate_v1_to_v2(data)
                self._save_installed(data)
            return data
        return {"schema_version": "2.0", "packages": {}}

    def _migrate_v1_to_v2(self, data):
        """Migrate installed.json from v1.0 to v2.0."""
        packages = data.get("packages", {})
        for pkg_id, info in packages.items():
            if "type" not in info:
                info["type"] = "python_package"
            if "source" not in info:
                info["source"] = "registry"
            if "name" not in info:
                info["name"] = pkg_id  # Old format used name as key
        data["schema_version"] = "2.0"
        return data

    def _save_installed(self, data=None):
        """Save installed.json."""
        if data is None:
            data = self._installed
        path = self._config.installed_json_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def install_package(self, zip_path, meta):
        """Install a package from a zip file.

        Args:
            zip_path: Path to the downloaded zip
            meta: Package information (dict) containing id, name, version, etc.
        """
        pkg_id = meta["id"]
        name = meta["name"]
        version = meta["version"]
        pkg_type = meta.get("type", "python_package")

        # Extraction destination (directory name uses name)
        package_dir = os.path.join(self._config.packages_dir, name)
        os.makedirs(package_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(package_dir)

        # Run install via Handler
        handler = get_handler(pkg_type)
        handler.install(package_dir, meta, self._env_manager)

        # Record in installed.json (key is UUID)
        info = PackageInfo(
            pkg_id=pkg_id,
            name=name,
            display_name=meta.get("display_name", name),
            version=version,
            pkg_type=pkg_type,
            entry_point=meta.get("entry_point", {}),
            path="packages/{}".format(name),
            source="registry",
            installed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self._installed["packages"][pkg_id] = info.to_installed_dict()
        self._save_installed()

    def uninstall_package(self, pkg_id):
        """Uninstall a package."""
        pkg_data = self._installed["packages"].get(pkg_id)
        if not pkg_data:
            return

        pkg_type = pkg_data.get("type", "python_package")
        package_dir = os.path.join(self._config.install_dir, pkg_data.get("path", ""))
        handler = get_handler(pkg_type)
        handler.uninstall(package_dir, pkg_data, self._env_manager)

        del self._installed["packages"][pkg_id]
        self._save_installed()

    def activate_all(self):
        """Activate all installed packages."""
        for pkg_id, pkg_data in self._installed.get("packages", {}).items():
            pkg_type = pkg_data.get("type", "python_package")
            package_dir = os.path.join(
                self._config.install_dir, pkg_data.get("path", "")
            )
            if not os.path.exists(package_dir):
                name = pkg_data.get("name", pkg_id)
                print("[Carton] Package dir not found, skipping: {}".format(name))
                continue
            handler = get_handler(pkg_type)
            handler.activate(package_dir, pkg_data, self._env_manager)

    def get_installed_packages(self):
        """Return the dictionary of installed packages. Keys are UUIDs."""
        return self._installed.get("packages", {})

    def get_installed_version(self, pkg_id):
        """Return the installed version of the specified package."""
        pkg = self._installed.get("packages", {}).get(pkg_id)
        if pkg:
            return pkg.get("version")
        return None

    def is_installed(self, pkg_id):
        return pkg_id in self._installed.get("packages", {})
