"""Origin base classes and value objects.

An :class:`Origin` describes where a package's bytes live. Each subclass
implements :meth:`list_versions` (what versions are available) and
:meth:`get_artifact` (URL + integrity for a specific version).

The :func:`origin_from_dict` factory dispatches on the ``type`` field of a
catalogue origin dict to the correct subclass. Unknown types raise
:class:`OriginError` so corrupted catalogues fail loud instead of silently
losing packages.
"""


class OriginError(RuntimeError):
    """Raised when an origin cannot resolve versions or artifacts.

    The caller (catalogue_client / downloader) decides whether to skip the
    package, surface a UI warning, or propagate the failure.
    """


class VersionMeta:
    """Metadata for one published version of a package.

    Mirrors the v5.0 ``version_entry`` schema so embedded origins map 1:1
    onto catalogue rows. Origins that resolve versions dynamically (github,
    url) populate the same fields from their respective sources.
    """

    def __init__(self, version, released_at="", changelog="",
                 maya_versions=None, platform=None, raw=None):
        self.version = version
        self.released_at = released_at
        self.changelog = changelog
        self.maya_versions = list(maya_versions or [])
        self.platform = list(platform or [])
        # Raw dict from the source so callers that need esoteric fields
        # (e.g. ``artifacts`` for plugin variants) can reach in without us
        # having to enumerate every field upfront.
        self.raw = dict(raw or {})

    def to_dict(self):
        d = {
            "version": self.version,
            "released_at": self.released_at,
            "changelog": self.changelog,
            "maya_versions": list(self.maya_versions),
            "platform": list(self.platform),
        }
        return d


class ArtifactRef:
    """A resolved artifact: where to download it and how to verify it.

    ``is_pinned`` is True iff ``sha256`` came from a trusted, pre-published
    source (embedded catalogue entry, GitHub Release SHA256SUMS, etc.). When
    False the value is either empty (TOFU pending) or a cached first-fetch
    value, and ``Config.strict_verify`` should reject the install.
    """

    def __init__(self, url, sha256="", size_bytes=0, is_pinned=False,
                 source_label=""):
        self.url = url
        self.sha256 = (sha256 or "").lower()
        self.size_bytes = int(size_bytes or 0)
        self.is_pinned = bool(is_pinned)
        # Human-readable hint for the UI ("GitHub Release asset",
        # "auto-generated tag archive", "embedded zip"). Surfaces in the
        # download confirmation dialog so users know what they're fetching.
        self.source_label = source_label


class Origin(object):
    """Base class for all origin implementations.

    Subclasses must set the class attribute ``type`` (one of
    ``"embedded"``, ``"github"``, ``"url"``, ``"local"``) and implement
    :meth:`list_versions`, :meth:`get_artifact`, and :classmethod:`from_dict`.
    """

    type = None

    def list_versions(self):
        raise NotImplementedError

    def get_artifact(self, version):
        raise NotImplementedError

    def to_dict(self):
        """Serialise back into a catalogue origin dict.

        Default implementation returns just ``{"type": <type>}`` — subclasses
        with extra config (repo, url, etc.) override.
        """
        return {"type": self.type}

    @classmethod
    def from_dict(cls, data, base_dir=""):
        raise NotImplementedError


def origin_from_dict(data, base_dir=""):
    """Factory: dispatch a catalogue origin dict to the right subclass.

    ``base_dir`` is the directory (or URL) of the parent catalogue.json,
    used by embedded origins to resolve relative ``download_url`` values.
    """
    if not isinstance(data, dict):
        raise OriginError("origin must be an object, got {!r}".format(type(data).__name__))
    type_ = data.get("type")
    if not type_:
        raise OriginError("origin missing required 'type' field")

    # Lazy imports to avoid base.py ↔ subclass circular import at module load.
    from carton.core.origins.embedded_origin import EmbeddedOrigin
    from carton.core.origins.github_origin import GithubOrigin

    registry = {
        EmbeddedOrigin.type: EmbeddedOrigin,
        GithubOrigin.type: GithubOrigin,
    }
    cls = registry.get(type_)
    if cls is None:
        raise OriginError("unsupported origin type: {!r}".format(type_))
    return cls.from_dict(data, base_dir=base_dir)
