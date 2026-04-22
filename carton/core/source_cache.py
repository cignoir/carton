"""On-disk cache for remote-source data.

Two kinds of entries live here:

1. **API responses** (under ``api/``) — JSON bodies + ETag from GitHub's
   REST API, keyed by URL. TTL-bounded so a long-lived Maya session
   eventually picks up upstream changes (default 1h, override via
   :class:`carton.core.config.Config` when we wire that through).

2. **Artifact SHA256** (under ``sha/``) — first-fetch sha256 values
   computed for unpinned origins (e.g. GitHub auto-generated tag
   archives). These are permanent: TOFU pins. Mismatch on a later fetch
   means either the upstream has been tampered with or the user wants to
   re-pin (we surface this in the UI rather than silently overwriting).

Cache lives at ``~/.carton/source_cache/`` by default. Callers pass an
explicit ``cache_dir`` so tests can use a temp directory.
"""

import hashlib
import json
import os
import time


_API_TTL_SECONDS = 3600  # 1 hour


def default_cache_dir():
    """Return the default cache directory under the user's home."""
    return os.path.join(os.path.expanduser("~"), ".carton", "source_cache")


def _key_to_path(cache_dir, kind, key):
    """Build a per-key cache file path under ``<cache_dir>/<kind>/``.

    Keys are hashed so URLs / paths with characters illegal on Windows
    (``:``, ``?``, ``*``) don't trip the filesystem.
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, kind, digest[:2], digest + ".json")


def _atomic_write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


class SourceCache(object):
    """Thin wrapper around the on-disk source cache directory."""

    def __init__(self, cache_dir=None, api_ttl_seconds=_API_TTL_SECONDS):
        self._dir = cache_dir or default_cache_dir()
        self._api_ttl = int(api_ttl_seconds)

    @property
    def cache_dir(self):
        return self._dir

    # ---- API response cache ---------------------------------------------

    def read_api(self, url):
        """Return ``(body, etag)`` for a cached API response, or ``(None, "")``.

        ``body`` is None when the cache is missing or expired. ``etag`` is
        returned even on expiry so the caller can do a conditional GET
        (``If-None-Match``) and reuse the body on a 304.
        """
        path = _key_to_path(self._dir, "api", url)
        if not os.path.exists(path):
            return None, ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError):
            return None, ""
        etag = payload.get("etag") or ""
        fetched_at = payload.get("fetched_at") or 0
        body = payload.get("body")
        if not isinstance(fetched_at, (int, float)):
            return None, etag
        if (time.time() - fetched_at) > self._api_ttl:
            return None, etag
        return body, etag

    def write_api(self, url, body, etag=""):
        """Store ``body`` (parsed JSON) + ``etag`` for ``url``."""
        path = _key_to_path(self._dir, "api", url)
        _atomic_write_json(path, {
            "url": url,
            "etag": etag or "",
            "fetched_at": time.time(),
            "body": body,
        })

    # ---- TOFU sha256 pin -------------------------------------------------

    def read_pinned_sha256(self, artifact_url):
        """Return the previously-recorded sha256 for ``artifact_url``, or ``""``."""
        path = _key_to_path(self._dir, "sha", artifact_url)
        if not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError):
            return ""
        return (payload.get("sha256") or "").lower()

    def write_pinned_sha256(self, artifact_url, sha256):
        """Record ``sha256`` as the trusted hash for ``artifact_url``.

        Once written, this hash is permanent — future downloads must
        match. Re-pinning (e.g. after upstream rotation) is an explicit
        UI flow, not a silent overwrite.
        """
        sha256 = (sha256 or "").lower()
        if not sha256:
            return
        path = _key_to_path(self._dir, "sha", artifact_url)
        _atomic_write_json(path, {
            "url": artifact_url,
            "sha256": sha256,
            "fetched_at": time.time(),
        })

    def forget_pinned_sha256(self, artifact_url):
        """Remove a pinned sha256 entry. Returns True if a file was deleted."""
        path = _key_to_path(self._dir, "sha", artifact_url)
        if not os.path.exists(path):
            return False
        try:
            os.remove(path)
            return True
        except OSError:
            return False
