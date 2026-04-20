"""Package download (supports both local files and URLs).

v5.0 adds :meth:`Downloader.download_artifact`, which takes an
:class:`carton.core.origins.ArtifactRef` and applies pinned/unpinned
semantics:

* ``is_pinned=True``  — sha256 is authoritative; mismatch is fatal.
* ``is_pinned=False`` + ``config.strict_verify=True``  — refused.
* ``is_pinned=False`` + cache has a prior pin  — verify against cache
  (TOFU subsequent fetch).
* ``is_pinned=False`` + cache empty  — download unverified, then compute
  + persist sha256 as the TOFU pin so the next fetch is checked.

The legacy :meth:`download` path is untouched so v4.0 install flows keep
working while consumers migrate over.
"""

import os
import shutil

from carton.compat_urllib import urlopen, URLError
from carton.core.hash_verify import compute_sha256, verify_sha256

_MAX_RETRIES = 3


class DownloadError(Exception):
    pass


def _is_local_path(path):
    if not path:
        return False
    if path.startswith(("http://", "https://")):
        return False
    return True


class Downloader:
    """Fetch package zip from a URL or local path."""

    def __init__(self, config):
        self._config = config

    def download_artifact(self, artifact_ref, dest_path, cache=None):
        """Fetch an artifact described by an :class:`ArtifactRef`.

        Wraps :meth:`download` with v5.0 pinned/unpinned policy. ``cache``
        is an optional :class:`carton.core.source_cache.SourceCache` used
        for TOFU (trust-on-first-use) sha256 pinning of unpinned origins.

        Args:
            artifact_ref: Resolved artifact (url + sha256 + is_pinned flag)
                from an :class:`Origin.get_artifact` call.
            dest_path: Destination path.
            cache: Optional SourceCache for TOFU pinning. None disables
                TOFU entirely — unpinned downloads run unverified.

        Returns:
            ``dest_path`` on success.

        Raises:
            DownloadError: On strict_verify rejection, sha256 mismatch,
                or underlying transport failure.
        """
        url = artifact_ref.url
        if not url:
            raise DownloadError("artifact has no URL")

        # Policy gate first — fail fast before touching the network.
        strict = bool(getattr(self._config, "strict_verify", False))
        if not artifact_ref.is_pinned and strict:
            raise DownloadError(
                "unpinned source rejected (strict_verify is on): {}".format(
                    artifact_ref.source_label or url
                )
            )

        # Decide the expected sha256 for this download.
        # Pinned: trust the ref's sha256 directly.
        # Unpinned + cache hit: verify against the previously pinned hash.
        # Unpinned + cache miss: no check at download time; we pin after.
        expected_sha256 = ""
        record_tofu = False
        if artifact_ref.is_pinned:
            expected_sha256 = (artifact_ref.sha256 or "").lower()
        elif cache is not None:
            cached = cache.read_pinned_sha256(url)
            if cached:
                expected_sha256 = cached
            else:
                record_tofu = True

        self.download(
            url, dest_path,
            expected_sha256=expected_sha256 or None,
            expected_size=artifact_ref.size_bytes or None,
        )

        # TOFU: first time we've seen this unpinned URL. Record the sha256
        # so any future fetch that drifts (GitHub archive format change,
        # tampering, etc.) surfaces as a verification failure instead of
        # silently succeeding.
        if record_tofu and cache is not None:
            try:
                digest = compute_sha256(dest_path)
            except OSError as e:
                raise DownloadError("TOFU sha256 compute failed: {}".format(e))
            cache.write_pinned_sha256(url, digest)

        return dest_path

    def download(self, url, dest_path, expected_sha256=None, expected_size=None):
        """Fetch a file from a URL or local path and verify its hash.

        Args:
            url: Download URL or local file path
            dest_path: Destination path
            expected_sha256: Expected SHA256 hash (skipped if None)
            expected_size: Expected file size (skipped if None)

        Returns:
            Destination path
        """
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        if expected_size:
            free = shutil.disk_usage(os.path.dirname(dest_path)).free
            if free < expected_size * 2:
                raise DownloadError(
                    "Insufficient disk space: need {}MB, have {}MB".format(
                        expected_size * 2 // (1024 * 1024),
                        free // (1024 * 1024),
                    )
                )

        if _is_local_path(url):
            return self._copy_local(url, dest_path, expected_sha256)
        else:
            return self._download_remote(url, dest_path, expected_sha256)

    def _copy_local(self, src_path, dest_path, expected_sha256):
        """Copy a local file."""
        resolved = os.path.normpath(src_path)
        if not os.path.exists(resolved):
            raise DownloadError("File not found: {}".format(resolved))

        shutil.copy2(resolved, dest_path)

        if expected_sha256:
            if not verify_sha256(dest_path, expected_sha256):
                os.remove(dest_path)
                raise DownloadError("SHA256 mismatch")

        return dest_path

    def _download_remote(self, url, dest_path, expected_sha256):
        """Download via HTTP."""
        last_error = None
        for attempt in range(1, _MAX_RETRIES + 1):
            tmp_path = dest_path + ".tmp"
            try:
                resp = urlopen(url, timeout=60)
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)

                if expected_sha256:
                    if not verify_sha256(tmp_path, expected_sha256):
                        os.remove(tmp_path)
                        raise DownloadError("SHA256 mismatch")

                os.replace(tmp_path, dest_path)
                return dest_path

            except DownloadError:
                raise
            except Exception as e:
                last_error = e
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                if attempt < _MAX_RETRIES:
                    import time
                    time.sleep(2 ** attempt)

        raise DownloadError(
            "Download failed after {} retries: {}".format(_MAX_RETRIES, last_error)
        )
