"""Package download (supports both local files and URLs)."""

import os
import shutil

try:
    from urllib.request import urlopen
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, URLError

from carton.core.hash_verify import verify_sha256

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
