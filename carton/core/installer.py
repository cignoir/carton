"""InstallManager — manages package install, uninstall, and activation."""

import json
import os
import zipfile
from datetime import datetime, timezone

from carton.core.handlers import get_handler
from carton.models.package_info import PackageInfo


class InstallManager:
    """Facade for package management using Handlers.

    Keys in ``installed.json`` are ``"<namespace>/<name>"`` for registry-sourced
    packages. Locally-registered scripts (My Tools) without a namespace are
    keyed by bare ``name``.
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
            return data
        return {"schema_version": "3.0", "packages": {}}

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
        namespace = meta.get("namespace", "")
        name = meta["name"]
        version = meta["version"]
        pkg_type = meta.get("type", "python_package")

        # Extraction destination: packages/<namespace>/<name> (or just <name> if no namespace)
        if namespace:
            rel_path = "packages/{}/{}".format(namespace, name)
        else:
            rel_path = "packages/{}".format(name)
        package_dir = os.path.join(self._config.install_dir, rel_path)
        os.makedirs(package_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(package_dir)

        # Read the inner package.json for the canonical entry_point. The
        # registry-side meta only carries identity + display fields; the inner
        # package.json is the source of truth for type/entry_point details.
        entry_point = meta.get("entry_point", {}) or {}
        inner_pkg_json = os.path.join(package_dir, "package.json")
        if os.path.exists(inner_pkg_json):
            try:
                with open(inner_pkg_json, "rb") as f:
                    # Use latin-1 to round-trip any pre-UTF-8 mojibake bytes
                    inner = json.loads(f.read().decode("latin-1"))
                if inner.get("entry_point"):
                    entry_point = inner["entry_point"]
                if inner.get("type"):
                    pkg_type = inner["type"]
            except (OSError, ValueError):
                pass

        handler = get_handler(pkg_type)
        handler.install(package_dir, meta, self._env_manager)

        info = PackageInfo(
            pkg_id=pkg_id,
            namespace=namespace,
            name=name,
            display_name=meta.get("display_name", name),
            version=version,
            pkg_type=pkg_type,
            entry_point=entry_point,
            path=rel_path,
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
