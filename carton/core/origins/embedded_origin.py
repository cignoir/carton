"""Embedded origin — packages whose artifacts live next to the catalogue.

This is the v4.0-style "registry hosts everything" layout. Versions and
artifacts are listed verbatim in the catalogue under ``origin.versions``;
``download_url`` may be a path relative to the catalogue.json directory or
an absolute URL.

Embedded origins are always pinned — the catalogue maintainer is the SoT
for sha256 / size_bytes.
"""

import os

from carton.compat_urllib import urljoin
from carton.core.origins.base import ArtifactRef, Origin, OriginError, VersionMeta


def _is_remote_base(base):
    return isinstance(base, str) and base.startswith(("http://", "https://"))


def _resolve_path(base_dir, rel):
    """Resolve ``rel`` against ``base_dir`` (URL or filesystem path)."""
    if not rel:
        return rel
    if rel.startswith(("http://", "https://")) or os.path.isabs(rel):
        return rel
    if _is_remote_base(base_dir):
        return urljoin(base_dir, rel)
    return os.path.normpath(os.path.join(base_dir or "", rel))


class EmbeddedOrigin(Origin):
    """Origin where the catalogue itself lists versions + artifacts."""

    type = "embedded"

    def __init__(self, versions=None, latest_version="", base_dir=""):
        # ``versions`` is the raw dict pulled out of catalogue origin.versions
        # so we don't have to reconstruct esoteric per-version fields like
        # ``artifacts`` (used by plugin packages for platform variants).
        self._versions = dict(versions or {})
        self._latest = latest_version or ""
        self._base_dir = base_dir or ""

    @classmethod
    def from_dict(cls, data, base_dir=""):
        if data.get("type") != cls.type:
            raise OriginError("expected embedded origin, got {!r}".format(data.get("type")))
        return cls(
            versions=data.get("versions") or {},
            latest_version=data.get("latest_version") or "",
            base_dir=base_dir,
        )

    def to_dict(self):
        d = {"type": self.type, "versions": dict(self._versions)}
        if self._latest:
            d["latest_version"] = self._latest
        return d

    def list_versions(self):
        out = {}
        for ver, raw in self._versions.items():
            if not isinstance(raw, dict):
                continue
            out[ver] = VersionMeta(
                version=ver,
                released_at=raw.get("released_at", ""),
                changelog=raw.get("changelog", ""),
                maya_versions=raw.get("maya_versions", []),
                platform=raw.get("platform", []),
                raw=raw,
            )
        return out

    def latest_version(self):
        if self._latest and self._latest in self._versions:
            return self._latest
        # Fall back to lexicographic max — callers that care about
        # semver ordering should sort themselves.
        if not self._versions:
            return ""
        return sorted(self._versions.keys())[-1]

    def get_artifact(self, version):
        info = self._versions.get(version)
        if not isinstance(info, dict):
            raise OriginError("embedded origin has no version {!r}".format(version))
        url = info.get("download_url", "")
        if not url:
            raise OriginError(
                "embedded origin version {!r} missing download_url".format(version)
            )
        url = _resolve_path(self._base_dir, url)
        sha256 = (info.get("sha256") or "").lower()
        return ArtifactRef(
            url=url,
            sha256=sha256,
            size_bytes=info.get("size_bytes", 0),
            # Embedded artifacts are author-managed — sha256 published by
            # the catalogue maintainer is the SoT.
            is_pinned=bool(sha256),
            source_label="embedded",
        )
