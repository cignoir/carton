"""Package information model."""


class PackageInfo:
    """Package information constructed from registry.json / installed.json."""

    def __init__(
        self,
        pkg_id,
        name,
        display_name,
        version,
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
    ):
        self.id = pkg_id
        self.name = name
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

    @classmethod
    def from_registry_entry(cls, pkg_id, pkg_data, version_key=None):
        """Create from a registry.json entry. Key is UUID."""
        version_key = version_key or pkg_data.get("latest_version", "0.0.0")
        version_info = pkg_data.get("versions", {}).get(version_key, {})
        return cls(
            pkg_id=pkg_id,
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
        """Create from an installed.json entry. Key is UUID."""
        return cls(
            pkg_id=pkg_id,
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            version=data.get("version", "0.0.0"),
            pkg_type=data.get("type", "python_package"),
            entry_point=data.get("entry_point", {}),
            path=data.get("path", ""),
            source=data.get("source", "registry"),
            installed_at=data.get("installed_at", ""),
            local_path=data.get("local_path", ""),
        )

    def to_installed_dict(self):
        """Dictionary for writing to installed.json."""
        d = {
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
        return d
