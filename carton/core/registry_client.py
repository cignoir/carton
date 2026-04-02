"""Multi-registry client."""

import json
import os


class RegistryClient:
    """Load multiple local registries and return them merged.

    Attaches _registry_name and _registry_base_dir to each package data entry.
    Also resolves relative paths in download_url.
    """

    def __init__(self, config):
        self._config = config
        self._packages = {}

    def fetch(self):
        """Load all registries and merge packages."""
        self._packages = {}
        for entry in self._config.registries:
            self._load_registry(entry)

    def _load_registry(self, entry):
        """Load a single registry."""
        path = os.path.normpath(entry.path)
        if not os.path.exists(path):
            print("[Carton] Registry not found: {} ({})".format(entry.name, path))
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print("[Carton] Registry read failed: {} ({})".format(entry.name, e))
            return

        base_dir = entry.base_dir
        packages = data.get("packages", {})

        for pkg_id, pkg_data in packages.items():
            if pkg_id in self._packages:
                # Duplicate UUID: prioritize the one loaded first
                continue
            item = dict(pkg_data)
            item["_registry_name"] = entry.name
            item["_registry_base_dir"] = base_dir

            # Resolve relative paths in download_url
            for ver_key, ver_info in item.get("versions", {}).items():
                dl_url = ver_info.get("download_url", "")
                if dl_url and not os.path.isabs(dl_url) and not dl_url.startswith(("http://", "https://")):
                    ver_info["download_url"] = os.path.normpath(
                        os.path.join(base_dir, dl_url)
                    )

            self._packages[pkg_id] = item

    def get_packages(self):
        """Return the merged package dictionary. Fetches if not yet loaded."""
        if not self._packages and self._config.registries:
            self.fetch()
        return self._packages

    def get_registry_names(self):
        """List of configured registry names."""
        return [r.name for r in self._config.registries]
