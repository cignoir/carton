"""Package information model."""

from carton.core.identity import split_pkg_id


class PackageInfo:
    """Package information constructed from registry.json / installed.json.

    Identity model: ``id == "<namespace>/<name>"``. Both are required for any
    package that participates in a registry; locally-registered tools that the
    user has not yet decided to publish may have an empty namespace.

    v4.0 source-of-truth split:
      * ``entry_point`` lives in the inner ``package.json`` for registry
        installs, and in this object only for My Tools (``source="local"``).
      * ``display_name`` lives on the registry for registry installs, and
        on this object only for My Tools.
      * ``sha256`` lives only on the registry — never persisted in
        installed.json.

    v5.0 addition: ``origin`` (optional) is an :class:`Origin` instance
    describing where this package's bytes live (embedded catalogue, GitHub
    repo, url, local path). v4.0 flows leave it ``None`` so behaviour is
    identical; v5.0 catalogue_client attaches it so downstream code can
    re-resolve artifacts on reinstall / upgrade without re-reading the
    catalogue.

    v5.0 addition: ``home_origin`` (optional) generalises ``home_registry``.
    Where ``home_registry`` could only name an embedded catalogue
    (``{"name": ..., "registry_id": ...}``), ``home_origin`` also expresses
    github/url/local publication targets (``{"type": "github",
    "repo": "..."}`` etc). The two fields co-exist on ``PackageInfo`` for
    the duration of the v5.0 transition; they are persisted side-by-side
    in installed.json / package.json, and no automatic synchronisation is
    performed — consumers in the alias period touch exactly one of them,
    and Step 4-B migrates them in-place.
    """

    def __init__(
        self,
        pkg_id=None,
        namespace="",
        name="",
        display_name="",
        version="0.0.0",
        pkg_type="python_package",
        description="",
        author="",
        maya_versions=None,
        entry_point=None,
        platform=None,
        tags=None,
        source="registry",
        path="",
        installed_at="",
        local_path="",
        home_registry=None,
        activated_paths=None,
        pinned=False,
        origin=None,
        home_origin=None,
    ):
        # Resolve identity. If pkg_id is given, prefer it; otherwise derive from ns/name.
        if pkg_id and "/" in pkg_id:
            ns_from_id, name_from_id = split_pkg_id(pkg_id)
            namespace = namespace or ns_from_id or ""
            name = name or name_from_id or ""
        self.namespace = (namespace or "").strip().lower()
        self.name = (name or "").strip().lower()
        if self.namespace and self.name:
            self.id = "{}/{}".format(self.namespace, self.name)
        else:
            # Personal-only package: no namespace yet, identify by bare name.
            self.id = self.name
        self.display_name = display_name
        self.version = version
        self.type = pkg_type
        self.description = description
        self.author = author
        self.maya_versions = maya_versions or []
        self.entry_point = entry_point or {}
        self.platform = platform or []
        self.tags = tags or []
        self.source = source
        self.path = path
        self.installed_at = installed_at
        self.local_path = local_path
        self.home_registry = home_registry or {}
        # v5.0: home_origin is the generalised form of home_registry — it
        # can name a github/url/local publication target in addition to
        # embedded catalogues. We store it verbatim (dict or empty dict);
        # callers that want the embedded-only legacy shape keep using
        # ``home_registry``. Sync between the two is intentionally not
        # performed at this layer — see class docstring.
        self.home_origin = home_origin or {}
        # {env_var: [path, ...]} recorded at install time. Used on
        # uninstall to restore the env to its pre-install state even if
        # the handler's uninstall logic is incomplete.
        self.activated_paths = activated_paths or {}
        # When True, this version is intentionally held — usually after a
        # rollback. Auto-update flows must skip pinned packages so the
        # user's choice isn't immediately undone.
        self.pinned = bool(pinned)
        self.origin = origin

    @classmethod
    def from_registry_entry(cls, pkg_id, pkg_data, version_key=None):
        """Create from a registry.json entry. Key is '<namespace>/<name>'.

        ``platform`` follows the v4.0 override rule: the version-level
        platform (if present) wins, otherwise the package-level platform
        is inherited.
        """
        version_key = version_key or pkg_data.get("latest_version", "0.0.0")
        version_info = pkg_data.get("versions", {}).get(version_key, {})
        platform = version_info.get("platform")
        if not platform:
            platform = pkg_data.get("platform", [])
        return cls(
            pkg_id=pkg_id,
            namespace=pkg_data.get("namespace", ""),
            name=pkg_data.get("name", ""),
            display_name=pkg_data.get("display_name", ""),
            version=version_key,
            pkg_type=pkg_data.get("type", "python_package"),
            description=pkg_data.get("description", ""),
            author=pkg_data.get("author", ""),
            maya_versions=version_info.get("maya_versions", []),
            platform=platform,
            tags=pkg_data.get("tags", []),
        )

    @classmethod
    def from_origin(cls, pkg_id, pkg_data, version_key=None, origin=None):
        """Create from a v5.0 catalogue package entry + its resolved Origin.

        ``pkg_data`` is the projected legacy-shape dict produced by
        :class:`carton.core.catalogue_client.CatalogueClient` — so scalar
        fields (``namespace``/``name``/``display_name``/...) and the
        per-version info still live under ``pkg_data["versions"]`` and can
        be parsed by :meth:`from_registry_entry`. ``origin`` is the
        :class:`Origin` instance backing the same package, captured here so
        downstream flows can re-resolve artifacts (reinstall, upgrade,
        pinned/unpinned check) without re-reading the catalogue.
        """
        info = cls.from_registry_entry(pkg_id, pkg_data, version_key=version_key)
        info.origin = origin
        return info

    @classmethod
    def from_installed_entry(cls, pkg_id, data):
        """Create from an installed.json entry."""
        origin = _origin_from_persisted(data.get("origin"))
        return cls(
            pkg_id=pkg_id,
            namespace=data.get("namespace", ""),
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            version=data.get("version", "0.0.0"),
            pkg_type=data.get("type", "python_package"),
            entry_point=data.get("entry_point", {}),
            path=data.get("path", ""),
            source=data.get("source", "registry"),
            installed_at=data.get("installed_at", ""),
            local_path=data.get("local_path", ""),
            home_registry=data.get("home_registry", {}),
            home_origin=data.get("home_origin", {}),
            activated_paths=data.get("activated_paths", {}),
            pinned=data.get("pinned", False),
            origin=origin,
        )

    def to_installed_dict(self):
        """Dictionary for writing to installed.json (v4.0 shape).

        ``entry_point`` and ``display_name`` are only emitted for My Tools
        (``source="local"``); registry-installed packages defer to the inner
        package.json and the registry respectively. ``sha256`` is never
        emitted — the registry is the SoT.
        """
        d = {
            "namespace": self.namespace,
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "installed_at": self.installed_at,
            "source": self.source,
        }
        if self.path:
            d["path"] = self.path
        if self.source == "local":
            # My Tools only — registry SoT for registry installs.
            if self.entry_point:
                d["entry_point"] = self.entry_point
            if self.display_name:
                d["display_name"] = self.display_name
        if self.local_path:
            d["local_path"] = self.local_path
        if self.home_registry:
            d["home_registry"] = self.home_registry
        if self.home_origin:
            d["home_origin"] = self.home_origin
        if self.activated_paths:
            d["activated_paths"] = self.activated_paths
        if self.pinned:
            d["pinned"] = True
        if self.origin is not None:
            origin_dict = _origin_to_persisted(self.origin)
            if origin_dict:
                d["origin"] = origin_dict
        return d


_ORIGIN_CATALOGUE_ONLY_KEYS = frozenset({"versions", "latest_version"})


def _origin_to_persisted(origin):
    """Serialise an :class:`Origin` for installed.json — identity fields only.

    Catalogue-derived metadata (``versions``, ``latest_version``) is
    intentionally dropped: keeping it here would shadow the live catalogue
    with stale values on the next reinstall / upgrade. We persist only the
    origin's locator ({type, repo, ref, url, ...}) so the re-resolution
    path knows where to look.
    """
    try:
        raw = origin.to_dict()
    except AttributeError:
        return None
    if not isinstance(raw, dict):
        return None
    return {k: v for k, v in raw.items() if k not in _ORIGIN_CATALOGUE_ONLY_KEYS}


def _origin_from_persisted(data):
    """Reconstruct an :class:`Origin` from its installed.json serialisation.

    Lazy import of :mod:`carton.core.origins` avoids a package_info →
    origins → (future) package_info cycle. Returns ``None`` on any parse
    failure so a corrupted entry never blocks loading installed.json.
    """
    if not isinstance(data, dict) or not data.get("type"):
        return None
    try:
        from carton.core.origins import origin_from_dict, OriginError
    except ImportError:
        return None
    try:
        return origin_from_dict(data)
    except OriginError:
        return None
