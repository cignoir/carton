"""Carton local configuration management."""

import json
import os
import shutil
import sys

from carton.compat_urllib import urlparse


def _is_url(path):
    """Check if a path is an HTTP/HTTPS URL."""
    return path.startswith(("http://", "https://"))


def _promote_display_names_to_catalogue(catalogues):
    """Migrate pre-v0.5 subscriber aliases into catalogue.json.

    Pre-v0.5 config.json stored a subscriber-picked ``name`` alongside
    each catalogue entry. v0.5 moves naming authority onto the catalogue
    itself (``catalogue.json.display_name``). On first load, each local
    catalogue whose display_name cache is populated but whose on-disk
    file has an empty ``display_name`` gets the cache promoted back into
    the file — this way the original author's choice (which survived in
    the old alias for the catalogue's creator on the machine they made
    it) isn't lost, and other subscribers will pick up the same label
    on their next fetch. Remote catalogues can't be mutated from here,
    so they keep the cached value on this machine and wait for the
    maintainer to stamp the remote file.

    Silent on any I/O or parse failure — a broken file should surface
    via the normal fetch path, not by failing startup.
    """
    for entry in catalogues:
        if entry.is_remote:
            continue
        if not entry.display_name:
            continue
        path = entry.path
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        existing = (data.get("display_name") or "").strip() if isinstance(data, dict) else ""
        if existing:
            continue
        data["display_name"] = entry.display_name
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            continue


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


class CatalogueEntry:
    """v5.0 catalogue configuration entry.

    ``catalogue_id`` is a client-side cache of the UUID stored inside the
    catalogue's ``catalogue.json``. It is populated on fetch (see
    :class:`carton.core.catalogue_client.CatalogueClient`) and persisted
    alongside ``path`` so duplicate detection can work before the first
    network round trip. Empty means "not yet known" — the hosted file is
    always the source of truth.

    ``display_name`` is a UI-only cache of the catalogue's ``display_name``
    field. The catalogue's ``catalogue.json`` owns the name (authors pick
    it at create time, like an npm package name); subscribers never
    override it. We keep a copy here so the sidebar / Settings list can
    render something before the first fetch completes and for local
    catalogues we never need to fetch at all. ``CatalogueClient`` refreshes
    this on every catalogue read.
    """

    def __init__(self, path, catalogue_id="", display_name=""):
        self.path = path if _is_url(path) else os.path.normpath(path)
        self.catalogue_id = (catalogue_id or "").strip().lower()
        self.display_name = display_name or ""

    def to_dict(self):
        d = {"path": self.path}
        if self.catalogue_id:
            d["catalogue_id"] = self.catalogue_id
        if self.display_name:
            d["display_name"] = self.display_name
        return d

    @classmethod
    def from_dict(cls, d):
        # Back-compat: pre-v5.0 config.json stored the subscriber-named
        # alias under ``name``. We treat it as the initial display_name
        # cache — the first fetch will overwrite with the authoritative
        # catalogue.json value. Local catalogue migration (writing the
        # alias back to catalogue.json when display_name is empty there)
        # happens in Config.load's post-load hook.
        display_name = d.get("display_name") or d.get("name", "")
        return cls(
            path=d.get("path", ""),
            catalogue_id=d.get("catalogue_id", ""),
            display_name=display_name,
        )

    def to_home_origin_meta(self):
        """Build a v5.0 ``home_origin`` payload (embedded-type) for this entry.

        Single source of truth so publisher / UI never construct home_origin
        dicts ad hoc. A :class:`CatalogueEntry` (=embedded catalogue) always
        emits the embedded variant, so the payload is
        ``{"type": "embedded", "catalogue_name": ..., "catalogue_id": ...,
        "hint": ...}``. The embedded name is a snapshot of ``display_name``
        at publish time — if the author later renames the catalogue,
        existing published packages keep the old label (catalogue_id is
        the identity key). Github/url/local origins construct their own
        payload at publish time and never go through this helper.
        """
        meta = {"type": "embedded"}
        if self.display_name:
            meta["catalogue_name"] = self.display_name
        if self.catalogue_id:
            meta["catalogue_id"] = self.catalogue_id
        if self.path and self.path != ".":
            meta["hint"] = self.path
        return meta

    def __str__(self):
        return "{} — {}".format(self.label, self.path)

    @property
    def label(self):
        """Best-effort display label: display_name, else basename, else path.

        UI call sites should use this instead of reading ``display_name``
        directly so a freshly-registered-but-not-yet-fetched remote
        catalogue still renders something meaningful (basename of the
        URL) rather than a blank string.
        """
        if self.display_name:
            return self.display_name
        if not self.path:
            return ""
        base = os.path.basename(self.path.rstrip("/\\"))
        return base or self.path

    @property
    def is_remote(self):
        """True if the catalogue is a remote URL."""
        return _is_url(self.path)

    @property
    def base_dir(self):
        """Base directory or URL for relative path resolution.

        For local: parent directory of catalogue.json
        For remote: parent URL of catalogue.json
        """
        if self.is_remote:
            return self.path.rsplit("/", 1)[0] + "/"
        return os.path.dirname(os.path.normpath(self.path))


class Config:
    """Read/write config.json."""

    def __init__(
        self,
        catalogues=None,
        install_dir=_DEFAULT_INSTALL_DIR,
        auto_check_updates=True,
        github_repo="cignoir/carton",
        language="auto",
        proxy="",
        active_profile="",
        strict_verify=True,
        profile_order=None,
    ):
        self.catalogues = catalogues or []
        self.install_dir = install_dir
        self.auto_check_updates = auto_check_updates
        self.github_repo = github_repo
        self.language = language
        # Name of the active runtime profile (see carton.core.profile_store).
        # Empty string means "use config.json directly". When set, the
        # overlay fields (catalogues / proxy / language / github_repo /
        # auto_check_updates) are persisted to the profile file too, so
        # switching profiles restores those values.
        self.active_profile = active_profile
        # When True, refuse to install any package whose catalogue entry
        # lacks a sha256, and treat hash mismatches as fatal (default
        # downloader already raises on mismatch). On by default — every
        # zip Carton publishes carries a sha256, so the only catalogues
        # this affects are very old or hand-rolled ones. Disable in
        # Settings if you need to install from such a catalogue.
        self.strict_verify = bool(strict_verify)
        # User-facing ordering of profiles in the sidebar dropdown.
        # Names not in this list (newly created profiles, or profiles
        # added on disk by another machine) are appended at the end on
        # display, and persisted on the next save().
        self.profile_order = list(profile_order or [])
        # HTTP(S) proxy URL, e.g. ``http://proxy.studio.internal:8080`` or
        # ``http://user:pass@host:8080``. Empty string means "don't override
        # whatever urllib picks up from the environment" — so users who
        # already have HTTP_PROXY / HTTPS_PROXY set keep working untouched.
        self.proxy = proxy

    @classmethod
    def load(cls, path=None):
        """Load config.json. Return defaults if not found."""
        is_canonical = path is None
        if path is None:
            path = default_config_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries_raw = data.get("catalogues", [])
            catalogues = [CatalogueEntry.from_dict(r) for r in entries_raw]
            # v0.5 one-shot: promote any subscriber-alias cache
            # (inherited from the legacy ``name`` key) into the local
            # catalogue.json itself. Subsequent loads become no-ops
            # once each catalogue owns a display_name on disk.
            if is_canonical:
                _promote_display_names_to_catalogue(catalogues)
            cfg = cls(
                catalogues=catalogues,
                install_dir=data.get("install_dir", _DEFAULT_INSTALL_DIR),
                auto_check_updates=data.get("auto_check_updates", True),
                github_repo=data.get("github_repo", "cignoir/carton"),
                language=data.get("language", "auto"),
                proxy=data.get("proxy", ""),
                active_profile=data.get("active_profile", ""),
                strict_verify=data.get("strict_verify", True),
                profile_order=data.get("profile_order", []),
            )
            # Only overlay the profile when loading from the canonical
            # location — explicit `path=` callers (tests, multi-config
            # tooling) shouldn't get pollution from the user's real
            # ~/.carton/profiles directory.
            if is_canonical:
                cfg._ensure_default_profile_and_overlay()
            return cfg
        # No config.json on disk: return raw defaults without touching
        # the profiles directory. The default profile gets materialised
        # on the first save() of an actual config.
        return cls()

    def _ensure_default_profile_and_overlay(self):
        """Make sure the active profile file exists and apply it.

        If ``active_profile`` is empty, normalise it to the canonical
        ``"default"`` name. If the corresponding profile file is missing
        (first run, or the user is upgrading from a pre-profile build),
        seed it from the current snapshot so the user's existing
        catalogues become the default profile's contents.
        """
        try:
            from carton.core import profile_store
            from carton.core.profile import InstallerProfile
        except Exception:
            return
        if not self.active_profile:
            self.active_profile = profile_store.DEFAULT_PROFILE_NAME
        # Make sure the canonical "default" profile exists at all times,
        # regardless of which profile happens to be active. Without this
        # an installer built from "viatora" produces an environment with
        # only viatora.json on disk and the user can never switch to a
        # blank baseline.
        if not profile_store.profile_exists(profile_store.DEFAULT_PROFILE_NAME):
            try:
                profile_store.save_profile(
                    profile_store.DEFAULT_PROFILE_NAME, InstallerProfile.blank(),
                )
            except Exception:
                pass
        if not profile_store.profile_exists(self.active_profile):
            # Only seed the active profile from a non-empty Config. If
            # the snapshot is empty avoid creating a permanent empty
            # profile that would later mask recovered data.
            if self.catalogues:
                try:
                    profile_store.save_profile(
                        self.active_profile, InstallerProfile.from_config(self),
                    )
                except Exception:
                    return
            else:
                return
        try:
            profile = profile_store.load_profile(self.active_profile)
            self.apply_profile(profile)
        except Exception:
            pass

    def save(self, path=None):
        """Write to config.json.

        The config file is always written to the canonical bootstrap location
        (default: ``~/Documents/maya/carton/config.json`` on Windows) so that
        ``load()`` can find it regardless of where ``install_dir`` points.
        """
        is_canonical = path is None
        if path is None:
            path = default_config_path()
        # Diagnostic: log every canonical save with caller info so we can
        # track down phantom writes that clobber the user's catalogues.
        if is_canonical:
            try:
                import traceback
                stack = traceback.format_stack()[-4:-1]
                print("[Carton.save] catalogues={} active_profile={!r}".format(
                    len(self.catalogues), self.active_profile))
                for line in stack:
                    print("  " + line.rstrip())
            except Exception:
                pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        # Mirror the overlay fields back into the active profile file so
        # next launch (or another machine pointed at the same profile dir)
        # picks up the changes. config.json's copy is just a snapshot.
        if is_canonical and self.active_profile:
            try:
                from carton.core import profile_store
                from carton.core.profile import InstallerProfile
                # Safety: if our in-memory catalogues list is empty but
                # the on-disk profile is not, refuse to clobber it. This
                # protects against any code path that briefly holds an
                # uninitialised Config and triggers a save before its
                # state is fully populated.
                if not self.catalogues and profile_store.profile_exists(self.active_profile):
                    try:
                        existing = profile_store.load_profile(self.active_profile)
                        if existing.catalogues:
                            return
                    except Exception:
                        pass
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

        try:
            common = os.path.commonpath([old_dir, new_dir])
        except ValueError:
            common = ""
        if common == old_dir:
            raise InstallDirChangeError(
                "New directory cannot be inside the current install directory."
            )

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
            "catalogues": [r.to_dict() for r in self.catalogues],
            "install_dir": self.install_dir,
            "auto_check_updates": self.auto_check_updates,
            "github_repo": self.github_repo,
            "language": self.language,
            "proxy": self.proxy,
            "active_profile": self.active_profile,
            "strict_verify": self.strict_verify,
            "profile_order": list(self.profile_order),
        }

    def apply_profile(self, profile):
        """Overlay the 5 profile fields onto this config (in-memory only).

        Does not call ``save()`` — caller decides when to persist. Used
        on startup (after loading config.json) and when the user switches
        profiles via the UI.
        """
        self.catalogues = [
            CatalogueEntry(
                path=r.path,
                catalogue_id=getattr(r, "catalogue_id", ""),
                display_name=getattr(r, "display_name", ""),
            )
            for r in profile.catalogues
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
        os.environ["http_proxy"] = self.proxy
        os.environ["https_proxy"] = self.proxy

    def add_catalogue(self, path, catalogue_id="", display_name=""):
        """Add a catalogue entry.

        ``display_name`` is optional — leave it empty and the first
        catalogue.json fetch will fill it in. Callers that already know
        the name (e.g. fresh-scaffolded local catalogue) can pass it to
        avoid a "Untitled" flash in the UI before the first fetch.
        """
        self.catalogues.append(
            CatalogueEntry(path, catalogue_id=catalogue_id, display_name=display_name),
        )

    def remove_catalogue(self, path_or_id):
        """Remove a catalogue entry by path or catalogue_id.

        Identity keys for catalogues are ``path`` and ``catalogue_id`` —
        ``display_name`` is just a label owned by the catalogue author
        and can collide across catalogues, so we never remove by name.
        """
        key = (path_or_id or "").strip()
        if not key:
            return
        key_path = key if _is_url(key) else os.path.normpath(key)
        key_id = key.lower()
        self.catalogues = [
            r for r in self.catalogues
            if r.path != key_path and (not r.catalogue_id or r.catalogue_id != key_id)
        ]

    def find_catalogue_by_id(self, catalogue_id):
        """Return the first CatalogueEntry whose ``catalogue_id`` matches, or None.

        Matches local and remote entries alike — callers that need a
        writable target should use :meth:`find_local_mirror` instead.
        """
        if not catalogue_id:
            return None
        cid = catalogue_id.strip().lower()
        for entry in self.catalogues:
            if entry.catalogue_id and entry.catalogue_id == cid:
                return entry
        return None

    def find_local_mirror(self, catalogue_id):
        """Return the first LOCAL CatalogueEntry with the given id, or None.

        Used by :class:`carton.core.publisher.Publisher` to route a publish
        against a remote entry to its writable local counterpart.
        """
        if not catalogue_id:
            return None
        cid = catalogue_id.strip().lower()
        for entry in self.catalogues:
            if entry.is_remote:
                continue
            if entry.catalogue_id and entry.catalogue_id == cid:
                return entry
        return None

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
