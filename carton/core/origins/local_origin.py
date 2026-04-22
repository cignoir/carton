"""Local origin — packages described by a ``package.json`` on disk.

Mirrors :class:`UrlOrigin` but the manifest lives on the local filesystem
instead of a remote URL:

    {"origin": {"type": "local", "path": "/abs/path/to/package.json"}}
    {"origin": {"type": "local", "path": "/abs/path/to/tool_dir"}}  # dir

``path`` may point directly at a ``package.json`` file or at a directory
containing one. The directory form is the common case — an author points
Carton at their source tree and can install / iterate without publishing.

Version enumeration:

* A single row, taken from ``package.json``'s ``version`` field. For
  history across versions, use a github or embedded origin (git tags vs.
  embedded catalogue versions). Local origin is the "dev / testing /
  air-gapped" escape hatch, not a version store.

Artifact resolution:

* ``package.json``'s ``download_url`` resolves relative to the manifest
  file's directory. Absolute paths (``/…``, ``C:\\…``) pass through.
* If ``sha256`` is listed the artifact is pinned; otherwise unpinned
  (SourceCache TOFU applies via the Downloader).
"""

import json
import os

from carton.core.origins.base import (
    ArtifactRef,
    Origin,
    OriginError,
    VersionMeta,
)


_MANIFEST_NAME = "package.json"


def _resolve_manifest_path(path):
    """Return the absolute path to a ``package.json``.

    Accepts either the manifest file itself or a directory containing it.
    Returns ``""`` when the resulting path is missing — callers handle
    the 'origin stale / moved' case without crashing.
    """
    if not path:
        return ""
    abs_path = os.path.abspath(os.path.expanduser(path))
    if os.path.isdir(abs_path):
        candidate = os.path.join(abs_path, _MANIFEST_NAME)
        return candidate if os.path.isfile(candidate) else ""
    return abs_path if os.path.isfile(abs_path) else ""


class LocalOrigin(Origin):
    """Origin backed by a filesystem ``package.json``."""

    type = "local"

    def __init__(self, path):
        if not path:
            raise OriginError("local origin requires a non-empty 'path'")
        self._path = path
        self._pkg_json = None  # Memoised on first load.
        self._manifest_path = None

    @classmethod
    def from_dict(cls, data, base_dir=""):
        if data.get("type") != cls.type:
            raise OriginError(
                "expected local origin, got {!r}".format(data.get("type"))
            )
        return cls(path=data.get("path", ""))

    def to_dict(self):
        return {"type": self.type, "path": self._path}

    @property
    def path(self):
        return self._path

    def _load_package_json(self):
        if self._pkg_json is not None:
            return self._pkg_json
        manifest = _resolve_manifest_path(self._path)
        self._manifest_path = manifest
        if not manifest:
            self._pkg_json = {}
            return self._pkg_json
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            self._pkg_json = {}
            return self._pkg_json
        self._pkg_json = data if isinstance(data, dict) else {}
        return self._pkg_json

    def list_versions(self):
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
        data = self._load_package_json()
        pkg_version = (data.get("version") or "").strip()
        if not pkg_version or pkg_version != version:
            raise OriginError(
                "local origin at {!r} has no version {!r}".format(self._path, version)
            )
        artifact = data.get("download_url", "")
        if not artifact:
            raise OriginError(
                "local origin at {!r} missing download_url".format(self._path)
            )
        # Resolve relative to the manifest's directory so authors can
        # reference ``tool-1.0.0.zip`` next to ``package.json`` without
        # spelling out the absolute path.
        if not os.path.isabs(artifact):
            base_dir = os.path.dirname(self._manifest_path or self._path)
            artifact = os.path.normpath(os.path.join(base_dir, artifact))
        sha256 = (data.get("sha256") or "").lower()
        return ArtifactRef(
            url=artifact,
            sha256=sha256,
            size_bytes=data.get("size_bytes", 0),
            is_pinned=bool(sha256 and len(sha256) == 64),
            source_label="local origin (package.json)",
        )
