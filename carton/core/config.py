"""Carton local configuration management."""

import json
import os
import shutil
import sys

from carton.compat_urllib import urlparse


def _is_url(path):
    """Check if a path is an HTTP/HTTPS URL."""
    return path.startswith(("http://", "https://"))


def _detect_install_dir():
    """Return the default install_dir based on the OS."""
    if sys.platform == "win32":
        return os.path.expanduser("~/Documents/maya/carton")
    return os.path.expanduser("~/maya/carton")


_DEFAULT_INSTALL_DIR = _detect_install_dir()


def default_bootstrap_dir():
    """Return the fixed location of the Carton ``carton/`` Python package.

    This is the directory the bootstrap adds to ``sys.path`` and where
    ``pending_update.json`` + its staged zip live. It never moves, even if
    the user reconfigures ``install_dir`` — install_dir is purely a data
    directory (packages/, installed.json, caches), not a code directory.
    """
    return _DEFAULT_INSTALL_DIR


def default_config_path():
    """Return the canonical location of ``config.json``.

    The config file always lives at the default bootstrap location regardless
    of where ``install_dir`` points, so that we can find it on startup before
    we know the user's chosen install directory.
    """
    return os.path.join(default_bootstrap_dir(), "config.json")


class InstallDirChangeError(RuntimeError):
    """Raised when switching install_dir fails (validation or move error)."""


class RegistryEntry:
    """Registry configuration entry."""

    def __init__(self, name, path):
        self.name = name
        self.path = path if _is_url(path) else os.path.normpath(path)

    def to_dict(self):
        return {"name": self.name, "path": self.path}

    @classmethod
    def from_dict(cls, d):
        return cls(name=d.get("name", ""), path=d.get("path", ""))

    def __str__(self):
        return "{} — {}".format(self.name, self.path)

    @property
    def is_remote(self):
        """True if the registry is a remote URL."""
        return _is_url(self.path)

    @property
    def base_dir(self):
        """Base directory or URL for relative path resolution.

        For local: parent directory of registry.json
        For remote: parent URL of registry.json
        """
        if self.is_remote:
            # "https://example.com/registry/registry.json" -> "https://example.com/registry/"
            return self.path.rsplit("/", 1)[0] + "/"
        return os.path.dirname(os.path.normpath(self.path))


class Config:
    """Read/write config.json."""

    def __init__(
        self,
        registries=None,
        install_dir=_DEFAULT_INSTALL_DIR,
        auto_check_updates=True,
        github_repo="cignoir/carton",
        language="auto",
        proxy="",
        active_profile="",
        strict_verify=False,
    ):
        self.registries = registries or []
        self.install_dir = install_dir
        self.auto_check_updates = auto_check_updates
        self.github_repo = github_repo
        self.language = language
        # Name of the active runtime profile (see carton.core.profile_store).
        # Empty string means "use config.json directly". When set, the
        # overlay fields (registries / proxy / language / github_repo /
        # auto_check_updates) are persisted to the profile file too, so
        # switching profiles restores those values.
        self.active_profile = active_profile
        # When True, refuse to install any package whose registry entry
        # lacks a sha256, and treat hash mismatches as fatal (default
        # downloader already raises on mismatch). Off by default so
        # legacy registries keep working; users opt in via Settings.
        self.strict_verify = bool(strict_verify)
        # HTTP(S) proxy URL, e.g. ``http://proxy.studio.internal:8080`` or
        # ``http://user:pass@host:8080``. Empty string means "don't override
        # whatever urllib picks up from the environment" — so users who
        # already have HTTP_PROXY / HTTPS_PROXY set keep working untouched.
        self.proxy = proxy

    @classmethod
    def load(cls, path=None):
        """Load config.json. Return defaults if not found."""
        if path is None:
            path = default_config_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            registries = [RegistryEntry.from_dict(r) for r in data.get("registries", [])]
            cfg = cls(
                registries=registries,
                install_dir=data.get("install_dir", _DEFAULT_INSTALL_DIR),
                auto_check_updates=data.get("auto_check_updates", True),
                github_repo=data.get("github_repo", "cignoir/carton"),
                language=data.get("language", "auto"),
                proxy=data.get("proxy", ""),
                active_profile=data.get("active_profile", ""),
                strict_verify=data.get("strict_verify", False),
            )
            # If a profile is active, overlay its values on top of the
            # snapshot stored in config.json. The snapshot is kept in sync
            # by save() so a missing profile file falls back gracefully.
            if cfg.active_profile:
                try:
                    from carton.core import profile_store
                    profile = profile_store.load_profile(cfg.active_profile)
                    cfg.apply_profile(profile)
                except Exception:
                    pass
            return cfg
        return cls()

    def save(self, path=None):
        """Write to config.json.

        The config file is always written to the canonical bootstrap location
        (default: ``~/Documents/maya/carton/config.json`` on Windows) so that
        ``load()`` can find it regardless of where ``install_dir`` points.
        """
        if path is None:
            path = default_config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        # Mirror the overlay fields back into the active profile file so
        # next launch (or another machine pointed at the same profile dir)
        # picks up the changes. config.json's copy is just a snapshot.
        if self.active_profile:
            try:
                from carton.core import profile_store
                from carton.core.profile import InstallerProfile
                profile_store.save_profile(
                    self.active_profile, InstallerProfile.from_config(self),
                )
            except Exception:
                pass

    def change_install_dir(self, new_dir):
        """Move Carton's install directory to ``new_dir`` and persist the change.

        Moves ``packages/``, ``installed.json``, ``.staging/`` and
        ``.icon_cache/`` from the current ``install_dir`` to ``new_dir``. The
        sys.path / MAYA_SCRIPT_PATH entries already registered by the current
        Maya session point at the old directory, so the caller MUST prompt
        the user to restart Maya after this returns.

        Raises :class:`InstallDirChangeError` on any validation or I/O
        failure. On success, ``self.install_dir`` is updated and ``save()``
        is called.
        """
        if not new_dir:
            raise InstallDirChangeError("New install directory is empty.")
        new_dir = os.path.abspath(os.path.expanduser(new_dir))
        old_dir = os.path.abspath(self.install_dir)

        if new_dir == old_dir:
            return  # No-op

        # Disallow nesting: moving into a subdir of the old tree would make
        # the move infinite/ambiguous.
        try:
            common = os.path.commonpath([old_dir, new_dir])
        except ValueError:
            common = ""
        if common == old_dir:
            raise InstallDirChangeError(
                "New directory cannot be inside the current install directory."
            )

        # New dir must either not exist, or exist and be empty. We refuse to
        # merge into a populated directory to avoid clobbering unrelated
        # files.
        if os.path.exists(new_dir):
            if not os.path.isdir(new_dir):
                raise InstallDirChangeError(
                    "Destination exists and is not a directory: {}".format(new_dir)
                )
            if os.listdir(new_dir):
                raise InstallDirChangeError(
                    "Destination directory is not empty: {}".format(new_dir)
                )
        else:
            try:
                os.makedirs(new_dir)
            except OSError as e:
                raise InstallDirChangeError(
                    "Cannot create destination: {}".format(e)
                )

        # Move each known subpath individually so we never touch files in
        # the old install_dir that Carton doesn't own (e.g. the user put
        # their install_dir = ~/maya and we'd otherwise nuke their shelves).
        _MOVE_ITEMS = ("packages", "installed.json", ".staging", ".icon_cache")
        moved = []
        try:
            for item in _MOVE_ITEMS:
                src = os.path.join(old_dir, item)
                if not os.path.exists(src):
                    continue
                dst = os.path.join(new_dir, item)
                shutil.move(src, dst)
                moved.append((src, dst))
        except (OSError, shutil.Error) as e:
            # Roll back anything we already moved so the old location is
            # usable again.
            for src, dst in moved:
                try:
                    shutil.move(dst, src)
                except Exception:
                    pass
            raise InstallDirChangeError("Failed to move files: {}".format(e))

        self.install_dir = new_dir
        try:
            self.save()
        except OSError as e:
            raise InstallDirChangeError(
                "Files moved but config.json save failed: {}".format(e)
            )

    def to_dict(self):
        return {
            "registries": [r.to_dict() for r in self.registries],
            "install_dir": self.install_dir,
            "auto_check_updates": self.auto_check_updates,
            "github_repo": self.github_repo,
            "language": self.language,
            "proxy": self.proxy,
            "active_profile": self.active_profile,
            "strict_verify": self.strict_verify,
        }

    def apply_profile(self, profile):
        """Overlay the 5 profile fields onto this config (in-memory only).

        Does not call ``save()`` — caller decides when to persist. Used
        on startup (after loading config.json) and when the user switches
        profiles via the UI.
        """
        self.registries = [
            RegistryEntry(name=r.name, path=r.path) for r in profile.registries
        ]
        self.language = profile.language
        self.auto_check_updates = profile.auto_check_updates
        self.github_repo = profile.github_repo
        self.proxy = profile.proxy

    def apply_proxy_to_env(self):
        """Push ``self.proxy`` into HTTP_PROXY / HTTPS_PROXY for urllib.

        ``urllib`` picks proxy settings off these environment variables at
        request time, which is far simpler than installing a custom opener
        into every call site. An empty ``self.proxy`` leaves the
        environment alone so users with a pre-configured shell keep
        working. Call this at startup and whenever the setting changes.
        """
        if not self.proxy:
            return
        os.environ["HTTP_PROXY"] = self.proxy
        os.environ["HTTPS_PROXY"] = self.proxy
        # Lowercase variants for cross-platform tools that only check those.
        os.environ["http_proxy"] = self.proxy
        os.environ["https_proxy"] = self.proxy

    def add_registry(self, name, path):
        """Add a registry."""
        self.registries.append(RegistryEntry(name, path))

    def remove_registry(self, name):
        """Remove a registry by name."""
        self.registries = [r for r in self.registries if r.name != name]

    @property
    def packages_dir(self):
        return os.path.join(self.install_dir, "packages")

    @property
    def installed_json_path(self):
        return os.path.join(self.install_dir, "installed.json")

    @property
    def staging_dir(self):
        return os.path.join(self.install_dir, ".staging")

    @property
    def icon_cache_dir(self):
        return os.path.join(self.install_dir, ".icon_cache")
