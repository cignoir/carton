"""Self-update for Carton itself (GitHub Releases + deferred update strategy)."""

import json
import os
from datetime import datetime, timezone

from urllib.request import Request, urlopen
from urllib.error import URLError
import carton
from carton.core.config import default_bootstrap_dir
from carton.core.downloader import DownloadError
from carton.models.version import Version


def _asset_sha256(asset):
    """Extract the sha256 hex digest from a GitHub release asset.

    GitHub's release API reports a server-computed ``digest`` per asset
    ("sha256:<hex>"). Returns None when absent (older releases, GHES)."""
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1].strip().lower() or None
    return None


class SelfUpdater:
    """Check for Carton updates from GitHub Releases and stage them.

    Does not apply immediately; places in the staging area
    for carton_bootstrap.py to apply at the next Maya startup.
    """

    def __init__(self, config, downloader):
        self._config = config
        self._downloader = downloader
        self._github_api = "https://api.github.com/repos/{}/releases/latest".format(
            config.github_repo
        )

    def check_update(self):
        """Check the latest version from GitHub Releases.

        Returns:
            (new_version, download_url, sha256_or_None) or None
        """
        try:
            req = Request(self._github_api)
            req.add_header("Accept", "application/vnd.github.v3+json")
            resp = urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, ValueError) as e:
            print("[Carton] GitHub update check failed: {}".format(e))
            return None

        tag = data.get("tag_name", "")
        latest = tag.lstrip("v")
        if not latest:
            return None

        try:
            current = Version.parse(carton.__version__)
            remote = Version.parse(latest)
        except ValueError:
            return None

        if remote > current:
            # Find update zip from release assets (carton-v*.zip)
            download_url = None
            sha256 = None
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.startswith("carton-v") and name.endswith(".zip"):
                    download_url = asset.get("browser_download_url")
                    sha256 = _asset_sha256(asset)
                    break
            if not download_url:
                return None
            return (latest, download_url, sha256)

        return None

    def stage_update(self, version, download_url, expected_sha256=None):
        """Download a new version to staging.

        Args:
            version: New version string
            download_url: URL of the zip
            expected_sha256: Hash from the release asset digest. Verified
                at download time here, recorded in pending_update.json so
                the bootstrap re-verifies right before extracting — the
                staged zip may sit on disk for days between the two.

        Returns:
            True if staged successfully
        """
        if not download_url:
            raise RuntimeError("No download URL for update")

        if not expected_sha256 and getattr(self._config, "strict_verify", False):
            # Same policy gate as package installs: strict_verify refuses
            # anything it cannot verify — including Carton itself.
            raise DownloadError(
                "unpinned source rejected (strict_verify is on): "
                "carton self-update"
            )

        # Stage next to the carton/ Python package — NOT under install_dir.
        # install_dir may have been relocated by the user and is purely a
        # data directory; the bootstrap only looks for pending_update.json
        # in the fixed bootstrap location.
        bootstrap_dir = default_bootstrap_dir()
        staging_dir = os.path.join(bootstrap_dir, ".staging")
        os.makedirs(staging_dir, exist_ok=True)

        zip_name = "carton-{}.zip".format(version)
        staged_zip = os.path.join(staging_dir, zip_name)

        self._downloader.download(
            download_url, staged_zip, expected_sha256=expected_sha256,
        )

        # Write pending_update.json into bootstrap_dir
        pending = {
            "package": "carton",
            "version": version,
            "staged_zip": os.path.join(".staging", zip_name),
            "staged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if expected_sha256:
            pending["sha256"] = expected_sha256.lower()
        pending_path = os.path.join(bootstrap_dir, "pending_update.json")
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)

        return True

    def has_pending_update(self):
        path = os.path.join(default_bootstrap_dir(), "pending_update.json")
        return os.path.exists(path)

    def get_pending_version(self):
        path = os.path.join(default_bootstrap_dir(), "pending_update.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("version")
        return None
