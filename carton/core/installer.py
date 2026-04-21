"""InstallManager — manages package install, uninstall, and activation."""

import json
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone

from carton.core.handlers import get_handler
from carton.core.install_state import is_my_tools
from carton.core.migrations import (
    INSTALLED_SCHEMA_VERSION,
    migrate_installed_data,
)
from carton.models.package_info import PackageInfo


class InstallError(RuntimeError):
    """Raised when a package install fails.

    On failure, InstallManager.install_package restores the previous version
    if there was one, so catching this exception means the on-disk state is
    back to what it was before the install attempt.
    """


class InstallManager:
    """Facade for package management using Handlers.

    Keys in ``installed.json`` are ``"<namespace>/<name>"`` for registry-sourced
    packages. Locally-registered scripts (My Tools) without a namespace are
    keyed by bare ``name``.
    """

    def __init__(self, config, env_manager):
        self._config = config
        self._env_manager = env_manager
        self._installed = self._load_installed()

    def _load_installed(self):
        """Load installed.json. Auto-migrates pre-v4.0 files in place."""
        path = self._config.installed_json_path
        if not os.path.exists(path):
            return {"schema_version": INSTALLED_SCHEMA_VERSION, "packages": {}}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        migrated, was_migrated = migrate_installed_data(data)
        if was_migrated:
            # Persist on disk now (with backup) so subsequent reads are
            # already in the new shape and external tools see the new
            # schema_version.
            from carton.core.migrations import make_backup
            make_backup(path)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(migrated, f, indent=2, ensure_ascii=False)
        return migrated

    def _save_installed(self, data=None):
        """Save installed.json."""
        if data is None:
            data = self._installed
        path = self._config.installed_json_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def install_package(self, zip_path, meta):
        """Install a package from a zip file.

        The operation is transactional: if any step fails (bad zip, handler
        error, disk error), the on-disk state and installed.json are rolled
        back to the previous version (or to "not installed" for a fresh
        install). Raises :class:`InstallError` on failure.

        Args:
            zip_path: Path to the downloaded zip.
            meta: Package information (dict) containing id, name, version, etc.
        """
        pkg_id = meta["id"]
        rel_path, package_dir = self._resolve_package_dir(meta)
        backup_dir = self._snapshot_for_rollback(package_dir)
        prev_entry = self._installed.get("packages", {}).get(pkg_id)

        try:
            os.makedirs(package_dir, exist_ok=True)
            self._extract_zip(zip_path, package_dir)
            inner = self._read_inner_package_json(package_dir)

            # entry_point is no longer persisted in installed.json — it's
            # resolved from the inner package.json at launch time. We still
            # need ``pkg_type`` and the My Tools relink hint here.
            pkg_type = inner.get("type") or meta.get("type", "python_package")
            inner_source_path = inner.get("source_path", "") or ""
            inner_is_folder = inner.get("is_folder")
            inner_home_origin = inner.get("home_origin")

            # If the publisher stamped the source path AND the same path
            # exists on this machine, treat the install as also a My Tools
            # registration: keep ``source="registry"`` (the bytes still
            # come from the registry) but record ``local_path`` so the UI
            # presents the entry as double-bound. This lets a user
            # reinstall Carton (or move to a fresh install_dir) and get
            # their My Tools entries back automatically.
            relink_local_path = ""
            if inner_source_path and os.path.exists(inner_source_path):
                relink_local_path = inner_source_path
                if inner_is_folder is None:
                    inner_is_folder = os.path.isdir(inner_source_path)

            activated_paths = self._run_handler_install(
                package_dir, meta, pkg_type,
            )

            entry_dict = self._build_install_entry(
                meta, pkg_type, rel_path,
                activated_paths, relink_local_path,
                inner_is_folder, inner_home_origin,
            )
            self._persist_install_entry(pkg_id, entry_dict, prev_entry)

        except Exception:
            self._rollback_filesystem(package_dir, backup_dir)
            raise

        # Success: drop the backup
        if backup_dir and os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)

    # ---- install_package helpers -----------------------------------------

    def _resolve_package_dir(self, meta):
        """Return ``(rel_path, absolute_package_dir)`` for the install target.

        Layout: ``packages/<namespace>/<name>`` (or just ``packages/<name>``
        for namespace-less packages).
        """
        namespace = meta.get("namespace", "")
        name = meta["name"]
        if namespace:
            rel_path = "packages/{}/{}".format(namespace, name)
        else:
            rel_path = "packages/{}".format(name)
        return rel_path, os.path.join(self._config.install_dir, rel_path)

    def _snapshot_for_rollback(self, package_dir):
        """Move an existing package_dir aside as a backup, returning its path.

        Returns None if no previous install exists. The rename is atomic on
        the same filesystem, so the live tree is gone in one step and we
        have a pristine destination for the new contents.
        """
        if not os.path.isdir(package_dir):
            return None
        backup_dir = "{}.carton-bak-{}".format(package_dir, int(time.time() * 1000))
        try:
            os.rename(package_dir, backup_dir)
        except OSError as e:
            raise InstallError(
                "Failed to prepare install (cannot snapshot previous version): {}".format(e)
            )
        return backup_dir

    def _extract_zip(self, zip_path, package_dir):
        """Validate and extract the package zip into ``package_dir``.

        Validates up front so BadZipFile surfaces before we've written
        anything into package_dir.
        """
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                bad = zf.testzip()
                if bad is not None:
                    raise InstallError("Corrupt zip — bad entry: {}".format(bad))
                zf.extractall(package_dir)
        except zipfile.BadZipFile as e:
            raise InstallError("Invalid or corrupt package zip: {}".format(e))
        except InstallError:
            raise
        except OSError as e:
            raise InstallError("Failed to extract package: {}".format(e))

    def _read_inner_package_json(self, package_dir):
        """Return the inner ``package.json`` as a dict, or ``{}`` if missing.

        The inner package.json is the source of truth for type/entry_point
        details — the registry-side meta only carries identity + display
        fields. Read errors are silently ignored: callers fall back to the
        registry meta.
        """
        inner_pkg_json = os.path.join(package_dir, "package.json")
        if not os.path.exists(inner_pkg_json):
            return {}
        try:
            with open(inner_pkg_json, "rb") as f:
                # Use latin-1 to round-trip any pre-UTF-8 mojibake bytes
                return json.loads(f.read().decode("latin-1"))
        except (OSError, ValueError):
            return {}

    def _run_handler_install(self, package_dir, meta, pkg_type):
        """Run the handler's install step and return its env-path diff.

        Snapshots env_manager state before the handler runs so we record
        exactly which sys.path / MAYA_*_PATH entries this install introduced.
        On uninstall we replay the diff to guarantee every introduced path
        is removed, even if the handler's own uninstall logic misses one.
        """
        handler = get_handler(pkg_type)
        env_before = self._env_manager.snapshot()
        try:
            handler.install(package_dir, meta, self._env_manager)
        except Exception as e:
            raise InstallError("Handler install failed: {}".format(e))
        return self._env_manager.diff_since(env_before)

    def _build_install_entry(self, meta, pkg_type, rel_path,
                              activated_paths, relink_local_path,
                              inner_is_folder, inner_home_origin):
        """Construct the installed.json entry dict for a successful install."""
        info = PackageInfo(
            pkg_id=meta["id"],
            namespace=meta.get("namespace", ""),
            name=meta["name"],
            version=meta["version"],
            pkg_type=pkg_type,
            path=rel_path,
            source="registry",
            installed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            activated_paths=activated_paths,
            pinned=meta.get("pinned", False),
            local_path=relink_local_path,
            home_origin=inner_home_origin or {},
        )
        entry_dict = info.to_installed_dict()
        if relink_local_path:
            if inner_is_folder is not None:
                entry_dict["is_folder"] = inner_is_folder
            # Stash the icon as an absolute path so My Tools can
            # render it without re-fetching from the registry.
            icon_resolved = meta.get("icon_resolved", "")
            if icon_resolved:
                entry_dict["icon"] = icon_resolved
        return entry_dict

    def _persist_install_entry(self, pkg_id, entry_dict, prev_entry):
        """Write the new entry to installed.json, reverting in-memory on failure."""
        self._installed["packages"][pkg_id] = entry_dict
        try:
            self._save_installed()
        except OSError as e:
            # Revert the in-memory registry change before rolling back
            # the filesystem in the outer except.
            if prev_entry is not None:
                self._installed["packages"][pkg_id] = prev_entry
            else:
                self._installed["packages"].pop(pkg_id, None)
            raise InstallError("Failed to persist installed.json: {}".format(e))

    def _rollback_filesystem(self, package_dir, backup_dir):
        """Restore the previous version (or clean up) after an install failure.

        Best-effort: rollback errors are logged but swallowed so the
        original cause still reaches the caller.
        """
        try:
            if os.path.isdir(package_dir):
                shutil.rmtree(package_dir, ignore_errors=True)
        except Exception as ce:
            print("[Carton] rollback cleanup failed: {}".format(ce))
        if backup_dir and os.path.isdir(backup_dir):
            try:
                os.rename(backup_dir, package_dir)
            except OSError as ce:
                print("[Carton] rollback restore failed: {}".format(ce))

    def uninstall_package(self, pkg_id):
        """Uninstall a package.

        Double-bound entries (registry-installed AND My Tools-registered,
        identified by ``source="registry"`` plus a non-empty ``local_path``)
        are demoted to pure My Tools (``source="local"``) instead of being
        removed — the registration is the user's data and shouldn't get
        wiped along with the registry bytes.
        """
        pkg_data = self._installed["packages"].get(pkg_id)
        if not pkg_data:
            return

        pkg_type = pkg_data.get("type", "python_package")
        package_dir = os.path.join(self._config.install_dir, pkg_data.get("path", ""))
        handler = get_handler(pkg_type)
        handler.uninstall(package_dir, pkg_data, self._env_manager)

        # Replay the env diff recorded at install time. The handler's own
        # uninstall has usually already removed these, in which case the
        # calls here are no-ops (remove_tracked is idempotent). This catches
        # any paths the handler missed — legacy entries without recorded
        # activated_paths just skip this step.
        activated = pkg_data.get("activated_paths") or {}
        if activated:
            self._env_manager.remove_tracked(activated)

        # Demote double-bound entries back to plain My Tools instead of
        # dropping them.
        if pkg_data.get("source") == "registry" and pkg_data.get("local_path"):
            pkg_data["source"] = "local"
            pkg_data["activated_paths"] = {}
            pkg_data.pop("path", None)
            self._save_installed()
            return

        del self._installed["packages"][pkg_id]
        self._save_installed()

    def activate_all(self):
        """Activate all installed packages."""
        for pkg_id, pkg_data in self._installed.get("packages", {}).items():
            pkg_type = pkg_data.get("type", "python_package")
            package_dir = os.path.join(
                self._config.install_dir, pkg_data.get("path", "")
            )
            if not os.path.exists(package_dir):
                name = pkg_data.get("name", pkg_id)
                print("[Carton] Package dir not found, skipping: {}".format(name))
                continue
            handler = get_handler(pkg_type)
            handler.activate(package_dir, pkg_data, self._env_manager)

    def get_installed_packages(self):
        """Return the dictionary of installed packages. Keys are UUIDs."""
        return self._installed.get("packages", {})

    def update_package_fields(self, pkg_id, fields):
        """Merge ``fields`` into an installed package entry and persist.

        No-op if ``pkg_id`` is not present. Returns True if the entry was
        updated, False otherwise.
        """
        packages = self._installed.get("packages", {})
        if pkg_id not in packages:
            return False
        packages[pkg_id].update(fields)
        self._save_installed()
        return True

    def rekey_package(self, old_id, new_id, fields=None):
        """Move an installed entry from ``old_id`` to ``new_id``.

        Optional ``fields`` are merged into the entry before it is re-keyed.
        ``home_origin`` is preserved if already set. No-op if ``old_id`` is
        not present. Returns True if the entry was re-keyed.
        """
        packages = self._installed.get("packages", {})
        if old_id not in packages:
            return False
        entry = packages.pop(old_id)
        if fields:
            entry.update(fields)
        packages[new_id] = entry
        self._save_installed()
        return True

    def get_installed_version(self, pkg_id):
        """Return the installed version of the specified package."""
        pkg = self._installed.get("packages", {}).get(pkg_id)
        if pkg:
            return pkg.get("version")
        return None

    def is_installed(self, pkg_id):
        """True if a package has registry-installed bytes on disk.

        Pure My Tools entries (``source="local"``) are reported as NOT
        installed — they reference original files in place and have no
        registry-managed bytes.
        """
        entry = self._installed.get("packages", {}).get(pkg_id)
        if not entry:
            return False
        return entry.get("source") == "registry"
