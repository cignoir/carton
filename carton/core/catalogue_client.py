"""Catalogue (v5.0) client — load + merge multiple package catalogues.

Supersedes the removed ``registry_client.RegistryClient``. Understands
both v4.0 registries (auto-migrated in memory on read) and v5.0
catalogues with the :class:`Origin` abstraction.

Output shape: a dict ``{pkg_id: pkg_data}`` carrying ``versions``,
``latest_version``, and ``_registry_*`` meta keys so UI / Updater /
Publisher consume it unchanged. The Origin instance backing each
package is exposed via ``get_origin(pkg_id)`` for callers that want to
re-resolve artifacts directly rather than through the projected dict.
"""

import json
import os
import zipfile

from carton.compat_urllib import urlopen, Request, URLError, urljoin, BytesIO
from carton.core.migrations import (
    CATALOGUE_FILENAME,
    LEGACY_REGISTRY_FILENAME,
    migrate_local_registry_file_to_catalogue,
    migrate_registry_to_catalogue,
)
from carton.core.origins import (
    EmbeddedOrigin,
    GithubOrigin,
    LocalOrigin,
    OriginError,
    UrlOrigin,
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
            ``config.catalogues`` as the list of catalogue entries
            (a :class:`~carton.core.config.CatalogueEntry`).
        cache: Optional :class:`SourceCache`. Defaults to one rooted at
            ``~/.carton/source_cache/``. Tests pass a temp dir.
    """

    def __init__(self, config, cache=None, personal_catalogue=None,
                 personal_catalogue_path=None):
        self._config = config
        self._cache = cache or SourceCache()
        self._packages = {}
        self._origins = {}
        self._catalogue_meta = {}  # pkg_id -> {"name": ..., "id": ..., "remote": bool}
        # Personal catalogue = local receptacle for URL-direct single-package
        # adds (see :mod:`carton.core.personal_catalogue`). Injection shape:
        #   * ``personal_catalogue=<instance>`` → use it directly
        #   * ``personal_catalogue_path=<path>`` → load from that path on fetch
        #   * both None → load from the default ``~/.carton/`` location
        # Tests typically pass an empty ``PersonalCatalogue()`` or a tmp_path
        # to stay hermetic from the developer's real home directory.
        self._personal_catalogue = personal_catalogue
        self._personal_catalogue_path = personal_catalogue_path

    # ---- public --------------------------------------------------------

    def fetch(self):
        """Reload all catalogues from scratch."""
        self._packages = {}
        self._origins = {}
        self._catalogue_meta = {}
        for entry in self._config.catalogues:
            try:
                self._load_entry(entry)
            except Exception as e:
                # Catalogue-level failures (network, parse) should never
                # bring down the whole client — log and move on so the
                # other catalogues still resolve.
                print("[Carton.catalogue] Failed to load {!r}: {}".format(
                    getattr(entry, "name", "<unknown>"), e))
        # Personal catalogue is merged LAST so subscribed catalogues win
        # on pkg_id collision — an official source should always trump a
        # user's ad-hoc URL-direct add.
        try:
            self._load_personal_catalogue()
        except Exception as e:
            print("[Carton.catalogue] Personal catalogue load failed: {}".format(e))

    def get_packages(self):
        """Return merged ``{pkg_id: pkg_data}``. Loads on first call."""
        if not self._packages and self._config.catalogues:
            self.fetch()
        return self._packages

    def get_origin(self, pkg_id):
        """Return the :class:`Origin` instance backing ``pkg_id``, or None."""
        return self._origins.get(pkg_id)

    # ---- entry loading -------------------------------------------------

    def _load_personal_catalogue(self):
        """Fold personal catalogue packages into the merged dict.

        Builds a synthetic :class:`CatalogueEntry` with ``name="Personal"``
        and an empty path so the existing :meth:`_merge_catalogue` path
        can consume it without special-casing. ``is_remote`` becomes
        False (the store lives under ``~/.carton/``), which is the
        honest answer — personal packages don't come from a subscribed
        URL. Consumers that want to distinguish personal from other
        local catalogues can match on ``_registry_name == 'Personal'``
        or on the fixed virtual entry path.
        """
        from carton.core.config import CatalogueEntry
        from carton.core.personal_catalogue import (
            PERSONAL_DISPLAY_NAME,
            PersonalCatalogue,
        )

        if self._personal_catalogue is None:
            self._personal_catalogue = PersonalCatalogue.load(
                self._personal_catalogue_path,
            )
        cat = self._personal_catalogue
        if not cat.packages:
            return

        virtual = CatalogueEntry(
            name=PERSONAL_DISPLAY_NAME,
            path="",
            catalogue_id=cat.catalogue_id,
        )
        self._merge_catalogue(virtual, cat.to_dict(), base_dir="")

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
        # Remote catalogues get their icons.zip pulled into the local
        # icon cache on fetch so the UI can render thumbnails without a
        # per-icon round trip. A missing icons.zip is fine — individual
        # icons are fetched lazily by the UI layer as a fallback.
        self._fetch_icons_archive(entry)

    def _fetch_icons_archive(self, entry):
        """Pull ``icons.zip`` next to the remote catalogue, if present.

        Extracts to ``config.icon_cache_dir`` and bounds the cache via
        :func:`carton.core.icon_cache.enforce_size_limit` so repeated
        fetches across many subscriptions don't blow out the cache.
        """
        cache_dir = self._config.icon_cache_dir
        base = entry.base_dir
        icons_url = urljoin(base, "icons.zip")
        try:
            req = Request(icons_url)
            resp = urlopen(req, timeout=10)
            data = resp.read()
            os.makedirs(cache_dir, exist_ok=True)
            with zipfile.ZipFile(BytesIO(data)) as zf:
                zf.extractall(cache_dir)
        except Exception:
            # Fall back to per-icon download handled by the UI layer.
            pass
        try:
            from carton.core.icon_cache import enforce_size_limit
            enforce_size_limit(cache_dir)
        except Exception:
            pass

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

        Uses :func:`read_registry_id` (UUID format validation) by passing
        the value through a temporary ``registry_id``-keyed dict — the
        helper itself is concerned only with UUID shape, not naming.
        """
        cid = read_registry_id({"registry_id": data.get("catalogue_id", "")})
        if cid:
            entry.catalogue_id = cid

    # ---- merge logic ---------------------------------------------------

    def _merge_catalogue(self, entry, data, base_dir):
        is_remote = entry.is_remote
        catalogue_name = entry.name
        catalogue_id = getattr(entry, "catalogue_id", "") or ""
        for pkg_id, pkg_data in (data.get("packages") or {}).items():
            if pkg_id in self._packages:
                # First catalogue wins — same dedupe rule as v0.4.
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

        The dict keys match the legacy v0.4 shape the UI / downloader /
        installer already consume (``_registry_*`` meta plus ``versions``
        /``latest_version``), so consumers didn't need changes when this
        client replaced the old one.
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
        elif isinstance(origin, (UrlOrigin, LocalOrigin)):
            # Url and local origins both expose a single "current"
            # version (the one written in their package.json). Only the
            # fetch mechanism differs (HTTP vs. disk); the projected
            # shape is identical, so consumers don't branch on type.
            versions = self._project_single_row_versions(origin)
            item["versions"] = versions
            if versions:
                item["latest_version"] = next(iter(versions.keys()))
            # Display metadata comes from the package.json itself
            # (manifest is SoT), so splat it onto ``item`` for card
            # rendering pre-install.
            self._hydrate_url_display(item, origin)
        else:
            item["versions"] = {}

        item["_registry_name"] = entry.name
        item["_registry_id"] = getattr(entry, "catalogue_id", "")
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
    def _project_single_row_versions(origin):
        """Return a versions dict for url / local origins.

        Both expose exactly one version (the current one in their
        ``package.json``). We project the returned ``ArtifactRef``
        fields into the same shape embedded / github versions use so
        consumers can keep reading ``download_url`` / ``sha256`` /
        ``_pinned`` without branching on origin type.
        """
        out = {}
        for ver, meta in origin.list_versions().items():
            entry = meta.to_dict()
            try:
                ref = origin.get_artifact(ver)
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

    # Backwards-compat alias: the name _project_url_versions was used
    # before LocalOrigin landed. External imports are unlikely (it's a
    # private method) but keep the old name working so anyone touching
    # the file in a half-applied patch doesn't get an AttributeError.
    _project_url_versions = _project_single_row_versions

    @staticmethod
    def _hydrate_url_display(item, origin):
        """Copy display metadata from the origin's package.json into ``item``.

        Personal-catalogue url / local entries are stored as just
        ``{"origin": {"type": "...", ...}}`` — they don't repeat
        display_name / description / icon inline. For the Library card
        to render something more informative than the raw pkg_id, we
        reach into the already-fetched package.json (cached on the
        origin instance) and splat its display fields into ``item``.
        Package-json fields win over any existing inline values because
        the manifest file is the v5.0 SoT.
        """
        loader = getattr(origin, "_load_package_json", None)
        if loader is None:
            return
        data = loader()
        if not isinstance(data, dict):
            return
        for field in (
            "namespace", "name", "display_name", "description", "type",
            "author", "icon", "tags", "platform", "entry_point",
        ):
            if field in data and data[field] is not None:
                item[field] = data[field]

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
