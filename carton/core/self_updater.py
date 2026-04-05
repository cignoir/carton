"""Self-update for Carton itself (GitHub Releases + deferred update strategy)."""

import json
import os
from datetime import datetime, timezone

from carton.compat_urllib import urlopen, Request, URLError

import carton
from carton.models.version import Version


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
            (new_version, download_url) or None
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
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.startswith("carton-v") and name.endswith(".zip"):
                    download_url = asset.get("browser_download_url")
                    break
            if not download_url:
                return None
            return (latest, download_url)

        return None

    def stage_update(self, version, download_url):
        """Download a new version to staging.

        Args:
            version: New version string
            download_url: URL of the zip

        Returns:
            True if staged successfully
        """
        if not download_url:
            raise RuntimeError("No download URL for update")

        staging_dir = self._config.staging_dir
        os.makedirs(staging_dir, exist_ok=True)

        zip_name = "carton-{}.zip".format(version)
        staged_zip = os.path.join(staging_dir, zip_name)

        self._downloader.download(download_url, staged_zip)

        # Write pending_update.json
        pending = {
            "package": "carton",
            "version": version,
            "staged_zip": os.path.join(".staging", zip_name),
            "staged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        pending_path = os.path.join(self._config.install_dir, "pending_update.json")
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)

        return True

    def has_pending_update(self):
        path = os.path.join(self._config.install_dir, "pending_update.json")
        return os.path.exists(path)

    def get_pending_version(self):
        path = os.path.join(self._config.install_dir, "pending_update.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("version")
        return None
