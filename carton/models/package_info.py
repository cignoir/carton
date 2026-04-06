"""Package information model."""

from carton.core.identity import make_pkg_id, split_pkg_id


class PackageInfo:
    """Package information constructed from registry.json / installed.json.

    Identity model: ``id == "<namespace>/<name>"``. Both are required for any
    package that participates in a registry; locally-registered tools that the
    user has not yet decided to publish may have an empty namespace.
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
        # {env_var: [path, ...]} recorded at install time. Used on
        # uninstall to restore the env to its pre-install state even if
        # the handler's uninstall logic is incomplete.
        self.activated_paths = activated_paths or {}

    @classmethod
    def from_registry_entry(cls, pkg_id, pkg_data, version_key=None):
        """Create from a registry.json entry. Key is '<namespace>/<name>'."""
        version_key = version_key or pkg_data.get("latest_version", "0.0.0")
        version_info = pkg_data.get("versions", {}).get(version_key, {})
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
            platform=pkg_data.get("platform", []),
            tags=pkg_data.get("tags", []),
        )

    @classmethod
    def from_installed_entry(cls, pkg_id, data):
        """Create from an installed.json entry."""
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
            activated_paths=data.get("activated_paths", {}),
        )

    def to_installed_dict(self):
        """Dictionary for writing to installed.json."""
        d = {
            "namespace": self.namespace,
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "installed_at": self.installed_at,
            "entry_point": self.entry_point,
            "path": self.path,
            "source": self.source,
        }
        if self.display_name:
            d["display_name"] = self.display_name
        if self.local_path:
            d["local_path"] = self.local_path
        if self.home_registry:
            d["home_registry"] = self.home_registry
        if self.activated_paths:
            d["activated_paths"] = self.activated_paths
        return d
