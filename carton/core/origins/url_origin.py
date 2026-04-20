"""URL origin — packages described by a remotely-hosted ``package.json``.

The catalogue entry carries a single ``url`` pointing at a JSON file:

    {"origin": {"type": "url", "url": "https://example.com/tool/package.json"}}

That URL returns a v4.0-style ``package.json`` (``namespace``, ``name``,
``version``, ``maya_versions``, etc.). The origin treats the ``version``
field as *the* current version — there is no version enumeration over an
arbitrary URL, so url-origin packages expose exactly one row.

Artifact resolution:

* If ``package.json`` has ``download_url``, that's the artifact URL.
  Relative paths resolve against the ``package.json`` URL (so an author
  can ship ``tool-1.0.0.zip`` next to their ``package.json`` and reference
  it as just ``"tool-1.0.0.zip"``).
* If ``package.json`` carries ``sha256`` (and it's a 64-char hex string),
  the artifact is pinned; the Downloader verifies against that SHA.
* Otherwise the artifact is unpinned — strict_verify rejects, and the
  Downloader's SourceCache TOFU-pins on first fetch.

Url origins are typically registered through ``Settings > Add >
"Single package by URL"`` and stored in
:mod:`carton.core.personal_catalogue`; they can also appear in a
subscribed catalogue whose maintainer wants to index a third-party tool
they don't host themselves.
"""

import json

from carton.compat_urllib import Request, URLError, urljoin, urlopen
from carton.core.origins.base import (
    ArtifactRef,
    Origin,
    OriginError,
    VersionMeta,
)


class UrlOrigin(Origin):
    """Origin backed by a remote ``package.json`` URL.

    Args:
        url: Absolute ``http(s)://`` URL to a ``package.json`` file.
    """

    type = "url"

    def __init__(self, url):
        if not url or not url.startswith(("http://", "https://")):
            raise OriginError(
                "url origin requires an absolute http(s) URL, got {!r}".format(url)
            )
        self._url = url
        # Memoise the fetched package.json for the lifetime of this
        # origin so list_versions → get_artifact doesn't round-trip
        # twice per rebuild. A None here means "not yet fetched"; an
        # empty dict means "fetched and failed / empty response" —
        # distinct so we don't retry after a failure within the same
        # session.
        self._pkg_json = None

    @classmethod
    def from_dict(cls, data, base_dir=""):
        if data.get("type") != cls.type:
            raise OriginError(
                "expected url origin, got {!r}".format(data.get("type"))
            )
        return cls(url=data.get("url", ""))

    def to_dict(self):
        return {"type": self.type, "url": self._url}

    @property
    def url(self):
        return self._url

    def _load_package_json(self):
        if self._pkg_json is not None:
            return self._pkg_json
        try:
            req = Request(self._url)
            req.add_header("Accept", "application/json")
            resp = urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, ValueError):
            self._pkg_json = {}
            return self._pkg_json
        self._pkg_json = data if isinstance(data, dict) else {}
        return self._pkg_json

    def list_versions(self):
        """Return ``{version: VersionMeta}`` — at most one row.

        url-origin packages ship a single current version inside their
        ``package.json``. Historical versions aren't reachable through
        this origin (the URL always returns "now"). Callers that need
        rollback across versions should use a github or embedded origin.
        """
        data = self._load_package_json()
        version = (data.get("version") or "").strip()
        if not version:
            return {}
        return {version: VersionMeta(
            version=version,
            released_at=data.get("released_at", ""),
            changelog=data.get("changelog", ""),
            maya_versions=data.get("maya_versions") or [],
            platform=data.get("platform") or [],
            raw=data,
        )}

    def get_artifact(self, version, package_name=""):
        """Resolve ``version`` into an :class:`ArtifactRef`.

        ``package_name`` is accepted for parity with github origin but
        not used — url origin carries only one artifact per URL.
        """
        data = self._load_package_json()
        pkg_version = (data.get("version") or "").strip()
        if not pkg_version or pkg_version != version:
            raise OriginError(
                "url origin at {!r} has no version {!r}".format(self._url, version)
            )
        artifact_url = data.get("download_url", "")
        if not artifact_url:
            raise OriginError(
                "url origin at {!r} missing download_url".format(self._url)
            )
        # Relative download_url resolves against the package.json URL so
        # authors can ship zips next to their manifest without needing
        # to repeat the full host in every entry.
        if not artifact_url.startswith(("http://", "https://")):
            artifact_url = urljoin(self._url, artifact_url)
        sha256 = (data.get("sha256") or "").lower()
        return ArtifactRef(
            url=artifact_url,
            sha256=sha256,
            size_bytes=data.get("size_bytes", 0),
            is_pinned=bool(sha256 and len(sha256) == 64),
            source_label="url origin (package.json)",
        )
