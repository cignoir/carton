"""Multi-registry client.

.. deprecated:: 0.5.0
   Use :class:`carton.core.catalogue_client.CatalogueClient`. The v5.0
   client understands both v4.0 registries (auto-migrated in memory)
   and v5.0 catalogues, and exposes the same ``fetch`` /
   ``get_packages`` surface this class provides. ``startup()`` already
   uses ``CatalogueClient`` — the only remaining consumers of
   ``RegistryClient`` are two legacy test files that will move over
   during Step 4-B. This module will be removed post v0.5.0 rollout.
"""

import json
import os
import warnings
import zipfile

from carton.compat_urllib import urlopen, Request, URLError, urljoin, BytesIO
from carton.core.migrations import make_backup, migrate_registry_data
from carton.core.registry_id import read_registry_id


class RegistryClient:
    """Load multiple local and remote registries and return them merged.

    Attaches _registry_name and _registry_base_dir to each package data entry.
    Also resolves relative paths in download_url.

    .. deprecated:: 0.5.0
       Use :class:`carton.core.catalogue_client.CatalogueClient`. See
       module docstring for context. Instantiating this class still
       works but emits a :class:`DeprecationWarning`.
    """

    def __init__(self, config):
        warnings.warn(
            "RegistryClient is deprecated as of Carton 0.5.0; use "
            "CatalogueClient from carton.core.catalogue_client. This "
            "shim will be removed after the v0.5.0 rollout.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._config = config
        self._packages = {}

    def fetch(self):
        """Load all registries and merge packages."""
        self._packages = {}
        for entry in self._config.registries:
            self._load_registry(entry)

    def _load_registry(self, entry):
        """Load a single registry (local or remote)."""
        if entry.is_remote:
            self._load_remote_registry(entry)
        else:
            self._load_local_registry(entry)

    def _load_local_registry(self, entry):
        """Load a registry from the local filesystem."""
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

        # Auto-migrate pre-v4.0 registries on read. We persist the result
        # so subsequent reads, the publisher, and admin CLIs all see the
        # new shape immediately.
        migrated, was_migrated = migrate_registry_data(data)
        if was_migrated:
            try:
                make_backup(path)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(migrated, f, indent=2, ensure_ascii=False)
            except OSError as e:
                print("[Carton] Registry migration write failed: {} ({})".format(
                    entry.name, e))
            data = migrated

        self._cache_registry_id(entry, data)
        self._merge_packages(entry, data)

    def _load_remote_registry(self, entry):
        """Load a registry from a remote URL."""
        try:
            req = Request(entry.path)
            req.add_header("Accept", "application/json")
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, ValueError) as e:
            print("[Carton] Remote registry failed: {} ({})".format(entry.name, e))
            return

        # Migrate in memory — we can't write back to a remote URL. Skip
        # the auto-stamp so a missing registry_id stays missing instead of
        # rotating through a fresh UUID on every fetch (which would break
        # mirror matching). Surface a warning so admins know to stamp the
        # canonical file.
        data, _ = migrate_registry_data(data, stamp_id=False)
        if not data.get("registry_id"):
            print(
                "[Carton] Remote registry {!r} has no registry_id — "
                "ask the maintainer to run `carton registry id <path> --stamp` "
                "so mirror matching can work.".format(entry.name)
            )

        self._cache_registry_id(entry, data)
        self._merge_packages(entry, data)
        self._fetch_icons_archive(entry)

    @staticmethod
    def _cache_registry_id(entry, data):
        """Copy ``registry_id`` from the loaded registry onto the entry.

        In-memory only — persistence happens via an explicit ``Config.save()``
        triggered by user actions (add/remove/edit). This way a failed or
        missing id doesn't silently clobber what's in config.json.
        """
        rid = read_registry_id(data)
        if rid:
            entry.registry_id = rid

    def _merge_packages(self, entry, data):
        """Merge packages from a loaded registry into the package dict."""
        base_dir = entry.base_dir
        is_remote = entry.is_remote
        packages = data.get("packages", {})

        for pkg_id, pkg_data in packages.items():
            if pkg_id in self._packages:
                # Duplicate UUID: prioritize the one loaded first
                continue
            item = dict(pkg_data)
            item["_registry_name"] = entry.name
            item["_registry_id"] = getattr(entry, "registry_id", "")
            item["_registry_base_dir"] = base_dir
            item["_registry_remote"] = is_remote

            # Resolve relative paths in download_url
            for ver_key, ver_info in item.get("versions", {}).items():
                dl_url = ver_info.get("download_url", "")
                if dl_url and not os.path.isabs(dl_url) and not dl_url.startswith(("http://", "https://")):
                    if is_remote:
                        ver_info["download_url"] = urljoin(base_dir, dl_url)
                    else:
                        ver_info["download_url"] = os.path.normpath(
                            os.path.join(base_dir, dl_url)
                        )

            self._packages[pkg_id] = item

    def _fetch_icons_archive(self, entry):
        """Download icons.zip from a remote registry and extract to icon cache."""
        cache_dir = self._config.icon_cache_dir
        icons_url = urljoin(entry.base_dir, "icons.zip")
        try:
            req = Request(icons_url)
            resp = urlopen(req, timeout=10)
            data = resp.read()
            os.makedirs(cache_dir, exist_ok=True)
            with zipfile.ZipFile(BytesIO(data)) as zf:
                zf.extractall(cache_dir)
        except Exception:
            # Fall back to per-icon download handled by UI layer
            pass
        # Keep the cache bounded regardless of whether this pull succeeded.
        from carton.core.icon_cache import enforce_size_limit
        enforce_size_limit(cache_dir)

    def get_packages(self):
        """Return the merged package dictionary. Fetches if not yet loaded."""
        if not self._packages and self._config.registries:
            self.fetch()
        return self._packages

    def get_registry_names(self):
        """List of configured registry names."""
        return [r.name for r in self._config.registries]
