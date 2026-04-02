"""Version comparison and update checking."""

from carton.models.version import Version


class UpdateInfo:
    """Update information."""

    def __init__(self, pkg_id, name, current_version, latest_version, version_info):
        self.pkg_id = pkg_id
        self.name = name
        self.current_version = current_version
        self.latest_version = latest_version
        self.version_info = version_info


class Updater:
    """Compare registry with local to detect updates."""

    def __init__(self, registry_client, install_manager):
        self._registry = registry_client
        self._install_mgr = install_manager

    def check_all_updates(self):
        """Check for updates across all installed packages.

        Returns:
            list[UpdateInfo]
        """
        updates = []
        reg_packages = self._registry.get_packages()
        installed = self._install_mgr.get_installed_packages()

        for pkg_id, pkg_data in installed.items():
            if pkg_data.get("source") == "local":
                continue

            registry_entry = reg_packages.get(pkg_id)
            if not registry_entry:
                continue

            latest = registry_entry.get("latest_version")
            current = pkg_data.get("version")

            if not latest or not current:
                continue

            try:
                if Version.parse(latest) > Version.parse(current):
                    version_info = registry_entry.get("versions", {}).get(latest, {})
                    name = registry_entry.get("name", pkg_data.get("name", ""))
                    updates.append(UpdateInfo(pkg_id, name, current, latest, version_info))
            except ValueError:
                continue

        return updates

    def check_update(self, pkg_id):
        """Check for updates for a specific package.

        Returns:
            UpdateInfo or None
        """
        reg_packages = self._registry.get_packages()
        registry_entry = reg_packages.get(pkg_id)
        if not registry_entry:
            return None

        current = self._install_mgr.get_installed_version(pkg_id)
        if not current:
            return None

        latest = registry_entry.get("latest_version")
        if not latest:
            return None

        try:
            if Version.parse(latest) > Version.parse(current):
                version_info = registry_entry.get("versions", {}).get(latest, {})
                name = registry_entry.get("name", "")
                return UpdateInfo(pkg_id, name, current, latest, version_info)
        except ValueError:
            pass

        return None
