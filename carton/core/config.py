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
    """Registry / catalogue configuration entry.

    ``registry_id`` is a client-side cache of the UUID stored inside the
    registry's ``registry.json`` (or, under v5.0, the ``catalogue_id`` of
    its ``catalogue.json``). It is populated on fetch (see
    :class:`carton.core.registry_client.RegistryClient` /
    :class:`carton.core.catalogue_client.CatalogueClient`) and persisted
    alongside ``name`` / ``path`` so duplicate detection can work before
    the first network round trip. Empty means "not yet known" — the
    hosted file is always the source of truth.

    v5.0 transition: the class is additionally exposed at module scope
    as :class:`CatalogueEntry`, and carries a :attr:`catalogue_id`
    property that mirrors :attr:`registry_id`. Both names refer to the
    same underlying storage — callers can migrate to the new vocabulary
    at their own pace without breaking the old one. The ``catalogue_id``
    kwarg on :meth:`from_dict` is accepted too so config.json files
    written by a future v0.5+ UI already round-trip cleanly through an
    older reader.
    """

    def __init__(self, name, path, registry_id="", catalogue_id=""):
        self.name = name
        self.path = path if _is_url(path) else os.path.normpath(path)
        # Precedence: explicit registry_id wins if both are passed,
        # since every live call site in the code still uses that name.
        # The catalogue_id kwarg is purely a forward-compat seam for
        # profile/config files written after the rename lands.
        rid = registry_id or catalogue_id or ""
        self.registry_id = rid.strip().lower()

    @property
    def catalogue_id(self):
        """v5.0 alias for :attr:`registry_id` — same storage, new name.

        Reads return whatever ``registry_id`` currently holds. Writes go
        through the same normalisation (lowercase + strip) so either
        name is safe to set from callers that have already adopted the
        v5.0 vocabulary.
        """
        return self.registry_id

    @catalogue_id.setter
    def catalogue_id(self, value):
        self.registry_id = (value or "").strip().lower()

    def to_dict(self):
        d = {"name": self.name, "path": self.path}
        if self.registry_id:
            d["registry_id"] = self.registry_id
        return d

    @classmethod
    def from_dict(cls, d):
        # Accept both key names so a config.json that has already been
        # rewritten with ``catalogue_id`` deserialises cleanly. The
        # writer still emits ``registry_id`` — flipping the write side
        # is a later step once all v0.4 clients are gone.
        return cls(
            name=d.get("name", ""),
            path=d.get("path", ""),
            registry_id=d.get("registry_id", "") or d.get("catalogue_id", ""),
        )

    def to_home_meta(self):
        """Build a ``home_registry`` payload for embedding in package metadata.

        Single source of truth so publisher / script_manager / UI never
        construct home_registry dicts ad hoc — that's how the
        ``registry_id`` field used to drift between encode sites.
        """
        meta = {"name": self.name}
        if self.registry_id:
            meta["registry_id"] = self.registry_id
        # An empty path normalises to "." via os.path.normpath in __init__;
        # treat that as "no hint" so the meta dict stays minimal.
        if self.path and self.path != ".":
            meta["hint"] = self.path
        return meta

    def to_home_origin_meta(self):
        """Build a v5.0 ``home_origin`` payload (embedded-type) for this entry.

        Counterpart to :meth:`to_home_meta`. Where ``home_registry`` only
        expressed the legacy ``{name, registry_id, hint}`` shape, the v5.0
        ``home_origin`` is a tagged union over embedded/github/url/local —
        a :class:`CatalogueEntry` (=embedded catalogue) always emits the
        embedded variant, so the payload is
        ``{"type": "embedded", "catalogue_name": ..., "catalogue_id": ...,
        "hint": ...}``. Github/url origins construct their own payload at
        publish time and never go through this helper.

        Kept alongside ``to_home_meta`` for the alias period so consumers
        migrate one call site at a time; callers that have flipped to the
        v5.0 vocabulary get the new shape, and older callers keep
        receiving the legacy one.
        """
        meta = {"type": "embedded", "catalogue_name": self.name}
        if self.registry_id:
            meta["catalogue_id"] = self.registry_id
        if self.path and self.path != ".":
            meta["hint"] = self.path
        return meta

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


# v5.0 name for :class:`RegistryEntry`. Identity assignment — both names
# refer to the exact same class object, so ``isinstance(x, CatalogueEntry)``
# and ``isinstance(x, RegistryEntry)`` are interchangeable. Consumers can
# migrate to the new name as the surrounding code is touched; keeping both
# names working avoids a flag-day rename that would be impossible to land
# atomically across UI + core + tests.
CatalogueEntry = RegistryEntry


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
        strict_verify=True,
        profile_order=None,
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
        # downloader already raises on mismatch). On by default — every
        # zip Carton publishes carries a sha256, so the only registries
        # this affects are very old or hand-rolled ones. Disable in
        # Settings if you need to install from such a registry.
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
            registries = [RegistryEntry.from_dict(r) for r in data.get("registries", [])]
            cfg = cls(
                registries=registries,
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
        registries become the default profile's contents.
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
            if self.registries:
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
        # track down phantom writes that clobber the user's registries.
        if is_canonical:
            try:
                import traceback
                stack = traceback.format_stack()[-4:-1]
                print("[Carton.save] registries={} active_profile={!r}".format(
                    len(self.registries), self.active_profile))
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
                # Safety: if our in-memory registries list is empty but
                # the on-disk profile is not, refuse to clobber it. This
                # protects against any code path that briefly holds an
                # uninitialised Config and triggers a save before its
                # state is fully populated.
                if not self.registries and profile_store.profile_exists(self.active_profile):
                    try:
                        existing = profile_store.load_profile(self.active_profile)
                        if existing.registries:
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
            "profile_order": list(self.profile_order),
        }

    def apply_profile(self, profile):
        """Overlay the 5 profile fields onto this config (in-memory only).

        Does not call ``save()`` — caller decides when to persist. Used
        on startup (after loading config.json) and when the user switches
        profiles via the UI.
        """
        self.registries = [
            RegistryEntry(
                name=r.name, path=r.path,
                registry_id=getattr(r, "registry_id", ""),
            )
            for r in profile.registries
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

    def add_registry(self, name, path, registry_id=""):
        """Add a registry."""
        self.registries.append(RegistryEntry(name, path, registry_id))

    def remove_registry(self, name):
        """Remove a registry by name."""
        self.registries = [r for r in self.registries if r.name != name]

    def find_registry_by_id(self, registry_id):
        """Return the first RegistryEntry whose ``registry_id`` matches, or None.

        Matches local and remote entries alike — callers that need a
        writable target should use :meth:`find_local_mirror` instead.
        """
        if not registry_id:
            return None
        rid = registry_id.strip().lower()
        for entry in self.registries:
            if entry.registry_id and entry.registry_id == rid:
                return entry
        return None

    def find_local_mirror(self, registry_id):
        """Return the first LOCAL RegistryEntry with the given id, or None.

        Used by :class:`carton.core.publisher.Publisher` to route a publish
        against a remote entry to its writable local counterpart.
        """
        if not registry_id:
            return None
        rid = registry_id.strip().lower()
        for entry in self.registries:
            if entry.is_remote:
                continue
            if entry.registry_id and entry.registry_id == rid:
                return entry
        return None

    # ---- v5.0 catalogue-name aliases ------------------------------------
    # These are thin delegates to the registry-named surface. Same storage,
    # new vocabulary — consumers migrating to v5.0 terminology can call
    # ``config.catalogues``, ``config.find_catalogue_by_id(...)`` etc.
    # while the old names keep working until every call site is moved.

    @property
    def catalogues(self):
        """v5.0 alias for :attr:`registries` — same list, new name."""
        return self.registries

    @catalogues.setter
    def catalogues(self, value):
        self.registries = list(value) if value is not None else []

    def add_catalogue(self, name, path, catalogue_id=""):
        """v5.0 alias for :meth:`add_registry`."""
        self.add_registry(name, path, catalogue_id)

    def remove_catalogue(self, name):
        """v5.0 alias for :meth:`remove_registry`."""
        self.remove_registry(name)

    def find_catalogue_by_id(self, catalogue_id):
        """v5.0 alias for :meth:`find_registry_by_id`."""
        return self.find_registry_by_id(catalogue_id)

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
