"""Catalogue (v5.0) client — load + merge multiple package catalogues.

Coexists with :class:`carton.core.registry_client.RegistryClient` while
the rest of the codebase migrates over. The two clients can run side by
side: the registry client serves the legacy v4.0 ``registry.json`` shape
to consumers that haven't moved yet, while CatalogueClient understands
both v4.0 (auto-migrating in memory) and v5.0 catalogues with the new
:class:`Origin` abstraction.

Output shape: a dict ``{pkg_id: pkg_data}`` compatible with what the rest
of Carton already consumes from RegistryClient (``versions``,
``latest_version``, ``_registry_*`` meta keys). This keeps Phase A
non-breaking — UI / downloader / installer continue to work unchanged.
The Origin instances are exposed via ``get_origin(pkg_id)`` for code
that wants to use them directly.
"""

import json
import os

from carton.compat_urllib import urlopen, Request, URLError, urljoin
from carton.core.migrations import (
    CATALOGUE_FILENAME,
    LEGACY_REGISTRY_FILENAME,
    migrate_local_registry_file_to_catalogue,
    migrate_registry_to_catalogue,
)
from carton.core.origins import (
    EmbeddedOrigin,
    GithubOrigin,
    OriginError,
    origin_from_dict,
)
from carton.core.registry_id import read_registry_id
from carton.core.source_cache import SourceCache


def _is_remote_path(path):
    return isinstance(path, str) and path.startswith(("http://", "https://"))


def _normalise_catalogue_url(url):
    """Adjust a remote URL to point at catalogue.json if it ends in registry.json."""
    if not isinstance(url, str):
        return url
    if url.endswith("/" + LEGACY_REGISTRY_FILENAME):
        return url[: -len(LEGACY_REGISTRY_FILENAME)] + CATALOGUE_FILENAME
    return url


class CatalogueClient(object):
    """Load multiple local + remote catalogues and merge their packages.

    Args:
        config: :class:`carton.core.config.Config`. We read
            ``config.registries`` as the list of catalogue entries
            (still named ``RegistryEntry`` in Phase A).
        cache: Optional :class:`SourceCache`. Defaults to one rooted at
            ``~/.carton/source_cache/``. Tests pass a temp dir.
    """

    def __init__(self, config, cache=None):
        self._config = config
        self._cache = cache or SourceCache()
        self._packages = {}
        self._origins = {}
        self._catalogue_meta = {}  # pkg_id -> {"name": ..., "id": ..., "remote": bool}

    # ---- public --------------------------------------------------------

    def fetch(self):
        """Reload all catalogues from scratch."""
        self._packages = {}
        self._origins = {}
        self._catalogue_meta = {}
        for entry in self._config.registries:
            try:
                self._load_entry(entry)
            except Exception as e:
                # Catalogue-level failures (network, parse) should never
                # bring down the whole client — log and move on so the
                # other catalogues still resolve.
                print("[Carton.catalogue] Failed to load {!r}: {}".format(
                    getattr(entry, "name", "<unknown>"), e))

    def get_packages(self):
        """Return merged ``{pkg_id: pkg_data}``. Loads on first call."""
        if not self._packages and self._config.registries:
            self.fetch()
        return self._packages

    def get_origin(self, pkg_id):
        """Return the :class:`Origin` instance backing ``pkg_id``, or None."""
        return self._origins.get(pkg_id)

    # ---- entry loading -------------------------------------------------

    def _load_entry(self, entry):
        if entry.is_remote:
            self._load_remote(entry)
        else:
            self._load_local(entry)

    def _load_local(self, entry):
        path = self._resolve_local_catalogue_path(entry.path)
        if not path or not os.path.exists(path):
            print("[Carton.catalogue] Not found: {} ({})".format(
                entry.name, entry.path))
            return

        # Auto-migrate legacy registry.json to catalogue.json on disk.
        if os.path.basename(path).lower() == LEGACY_REGISTRY_FILENAME:
            new_path = migrate_local_registry_file_to_catalogue(path)
            if new_path:
                path = new_path

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print("[Carton.catalogue] Read failed: {} ({})".format(entry.name, e))
            return

        # If this catalogue still parses as a v4.0 registry, migrate
        # in-memory (write-back happens via the file migrator above for
        # local files).
        data, _ = migrate_registry_to_catalogue(data)
        self._cache_catalogue_id(entry, data)
        self._merge_catalogue(entry, data, base_dir=os.path.dirname(path))

    def _load_remote(self, entry):
        url = _normalise_catalogue_url(entry.path)
        try:
            req = Request(url)
            req.add_header("Accept", "application/json")
            req.add_header("User-Agent", "Carton/0.5")
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, ValueError) as e:
            # Try the legacy registry.json URL as a fallback so that a
            # repo that has only been migrated on the producer side keeps
            # working from a stale subscription URL.
            if url != entry.path:
                try:
                    req = Request(entry.path)
                    req.add_header("Accept", "application/json")
                    req.add_header("User-Agent", "Carton/0.5")
                    resp = urlopen(req, timeout=15)
                    data = json.loads(resp.read().decode("utf-8"))
                except (URLError, OSError, ValueError) as e2:
                    print("[Carton.catalogue] Remote failed: {} ({})".format(
                        entry.name, e2))
                    return
            else:
                print("[Carton.catalogue] Remote failed: {} ({})".format(
                    entry.name, e))
                return

        # Migrate in memory only (no write-back to remote). stamp_id=False
        # so a missing UUID stays missing rather than rotating each fetch.
        data, _ = migrate_registry_to_catalogue(data, stamp_id=False)
        if not data.get("catalogue_id"):
            print(
                "[Carton.catalogue] Remote {!r} has no catalogue_id — "
                "ask the maintainer to stamp it so mirror matching can "
                "work.".format(entry.name)
            )
        self._cache_catalogue_id(entry, data)
        base_dir = url.rsplit("/", 1)[0] + "/"
        self._merge_catalogue(entry, data, base_dir=base_dir)

    @staticmethod
    def _resolve_local_catalogue_path(path):
        """Pick the right file to read from a local registry/catalogue path.

        Accepts paths pointing at ``catalogue.json``, ``registry.json``,
        or the parent directory. Prefers ``catalogue.json`` when both
        files exist (post-migration the legacy file is renamed to
        ``.bak-v0.4.<ms>`` so this only matters during the brief window
        between migration and rename).
        """
        if not path:
            return ""
        if os.path.isdir(path):
            cat = os.path.join(path, CATALOGUE_FILENAME)
            if os.path.exists(cat):
                return cat
            reg = os.path.join(path, LEGACY_REGISTRY_FILENAME)
            if os.path.exists(reg):
                return reg
            return ""
        # File path
        if os.path.basename(path).lower() == LEGACY_REGISTRY_FILENAME:
            sibling = os.path.join(os.path.dirname(path), CATALOGUE_FILENAME)
            if os.path.exists(sibling):
                return sibling
        return path

    @staticmethod
    def _cache_catalogue_id(entry, data):
        """Mirror ``catalogue_id`` from the loaded data onto the entry.

        Uses :func:`read_registry_id` (the v4.0 helper) since UUID format
        validation is identical between registry_id and catalogue_id.
        Stored on ``entry.registry_id`` for now so existing UI code that
        keys off that attribute keeps working.
        """
        cid = read_registry_id({"registry_id": data.get("catalogue_id", "")})
        if cid:
            entry.registry_id = cid

    # ---- merge logic ---------------------------------------------------

    def _merge_catalogue(self, entry, data, base_dir):
        is_remote = entry.is_remote
        catalogue_name = entry.name
        catalogue_id = getattr(entry, "registry_id", "") or ""
        for pkg_id, pkg_data in (data.get("packages") or {}).items():
            if pkg_id in self._packages:
                # First catalogue wins. Matches RegistryClient semantics.
                continue
            try:
                origin_dict = pkg_data.get("origin")
                if not origin_dict:
                    # Package has no origin field — defensive fallback to
                    # treat it as embedded with empty versions so the
                    # rest of the merge doesn't crash on broken data.
                    continue
                origin = origin_from_dict(origin_dict, base_dir=base_dir)
                if isinstance(origin, GithubOrigin):
                    origin.attach_cache(self._cache)
            except OriginError as e:
                print("[Carton.catalogue] Skipping {!r} from {!r}: {}".format(
                    pkg_id, catalogue_name, e))
                continue

            self._origins[pkg_id] = origin
            self._catalogue_meta[pkg_id] = {
                "name": catalogue_name,
                "id": catalogue_id,
                "remote": is_remote,
                "base_dir": base_dir,
            }

            self._packages[pkg_id] = self._build_legacy_shape(
                entry, pkg_id, pkg_data, origin, base_dir, is_remote,
            )

    def _build_legacy_shape(self, entry, pkg_id, pkg_data, origin, base_dir, is_remote):
        """Project a v5.0 package + origin into the dict shape consumers expect.

        Mirrors :meth:`RegistryClient._merge_packages` so the UI / downloader
        / installer can use either client interchangeably during the
        migration window.
        """
        item = {k: v for k, v in pkg_data.items() if k != "origin"}

        if isinstance(origin, EmbeddedOrigin):
            versions = self._project_embedded_versions(origin, base_dir, is_remote)
            item["versions"] = versions
            latest = origin.latest_version()
            if latest:
                item["latest_version"] = latest
        elif isinstance(origin, GithubOrigin):
            versions = self._project_github_versions(origin, pkg_id, pkg_data)
            item["versions"] = versions
            if versions:
                # Pick a stable "latest" by lexicographic order — semver
                # ordering is the consumer's job.
                item["latest_version"] = sorted(versions.keys())[-1]
        else:
            item["versions"] = {}

        item["_registry_name"] = entry.name
        item["_registry_id"] = getattr(entry, "registry_id", "")
        item["_registry_base_dir"] = base_dir
        item["_registry_remote"] = is_remote
        item["_origin"] = origin.to_dict()
        return item

    @staticmethod
    def _project_embedded_versions(origin, base_dir, is_remote):
        """Return a versions dict with ``download_url`` resolved to absolute."""
        out = {}
        for ver, meta in origin.list_versions().items():
            raw = dict(meta.raw or {})
            try:
                ref = origin.get_artifact(ver)
                raw["download_url"] = ref.url
                if ref.sha256:
                    raw["sha256"] = ref.sha256
                if ref.size_bytes:
                    raw["size_bytes"] = ref.size_bytes
            except OriginError:
                pass
            out[ver] = raw
        return out

    @staticmethod
    def _project_github_versions(origin, pkg_id, pkg_data):
        """Return a versions dict for github origins.

        Eagerly resolves the artifact URL for each version so consumers
        that read ``versions[v]['download_url']`` keep working. The
        pinned/unpinned flag travels via the ``_pinned`` mirror key.
        """
        package_name = pkg_data.get("name", "")
        if not package_name and "/" in pkg_id:
            package_name = pkg_id.split("/", 1)[1]

        out = {}
        for ver, meta in origin.list_versions().items():
            entry = meta.to_dict()
            try:
                ref = origin.get_artifact(ver, package_name=package_name)
                entry["download_url"] = ref.url
                if ref.sha256:
                    entry["sha256"] = ref.sha256
                if ref.size_bytes:
                    entry["size_bytes"] = ref.size_bytes
                entry["_pinned"] = ref.is_pinned
                entry["_source_label"] = ref.source_label
            except OriginError:
                continue
            out[ver] = entry
        return out
