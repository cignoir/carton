"""InstallManager — manages package install, uninstall, and activation."""

import json
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone

from carton.core.handlers import get_handler
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
        """Load installed.json."""
        path = self._config.installed_json_path
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        return {"schema_version": "3.0", "packages": {}}

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
        namespace = meta.get("namespace", "")
        name = meta["name"]
        version = meta["version"]
        pkg_type = meta.get("type", "python_package")

        # Extraction destination: packages/<namespace>/<name> (or just <name> if no namespace)
        if namespace:
            rel_path = "packages/{}/{}".format(namespace, name)
        else:
            rel_path = "packages/{}".format(name)
        package_dir = os.path.join(self._config.install_dir, rel_path)

        # --- Snapshot previous state for rollback ---------------------------
        # If a previous version is installed, move it aside as a backup. This
        # is a rename (fast, atomic on the same filesystem) so the live tree
        # is gone in one step and we have a pristine destination for the new
        # contents. If anything goes wrong below, we rename the backup back.
        backup_dir = None
        if os.path.isdir(package_dir):
            backup_dir = "{}.carton-bak-{}".format(package_dir, int(time.time() * 1000))
            try:
                os.rename(package_dir, backup_dir)
            except OSError as e:
                raise InstallError(
                    "Failed to prepare install (cannot snapshot previous version): {}".format(e)
                )

        prev_entry = self._installed.get("packages", {}).get(pkg_id)

        try:
            os.makedirs(package_dir, exist_ok=True)

            # Validate the zip up front so BadZipFile surfaces before we've
            # written anything into package_dir.
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    bad = zf.testzip()
                    if bad is not None:
                        raise InstallError(
                            "Corrupt zip — bad entry: {}".format(bad)
                        )
                    zf.extractall(package_dir)
            except zipfile.BadZipFile as e:
                raise InstallError("Invalid or corrupt package zip: {}".format(e))
            except InstallError:
                raise
            except OSError as e:
                raise InstallError("Failed to extract package: {}".format(e))

            # Read the inner package.json for the canonical entry_point. The
            # registry-side meta only carries identity + display fields; the
            # inner package.json is the source of truth for type/entry_point
            # details.
            entry_point = meta.get("entry_point", {}) or {}
            inner_pkg_json = os.path.join(package_dir, "package.json")
            if os.path.exists(inner_pkg_json):
                try:
                    with open(inner_pkg_json, "rb") as f:
                        # Use latin-1 to round-trip any pre-UTF-8 mojibake bytes
                        inner = json.loads(f.read().decode("latin-1"))
                    if inner.get("entry_point"):
                        entry_point = inner["entry_point"]
                    if inner.get("type"):
                        pkg_type = inner["type"]
                except (OSError, ValueError):
                    pass

            handler = get_handler(pkg_type)
            # Snapshot env_manager state before the handler runs so we can
            # record exactly which sys.path / MAYA_*_PATH entries this
            # install introduced. On uninstall we replay the diff to guarantee
            # every introduced path is removed, even if the handler's own
            # uninstall logic misses one.
            env_before = self._env_manager.snapshot()
            try:
                handler.install(package_dir, meta, self._env_manager)
            except Exception as e:
                raise InstallError("Handler install failed: {}".format(e))
            activated_paths = self._env_manager.diff_since(env_before)

            info = PackageInfo(
                pkg_id=pkg_id,
                namespace=namespace,
                name=name,
                display_name=meta.get("display_name", name),
                version=version,
                pkg_type=pkg_type,
                entry_point=entry_point,
                path=rel_path,
                source="registry",
                installed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                activated_paths=activated_paths,
                sha256=meta.get("sha256", ""),
                pinned=meta.get("pinned", False),
            )
            self._installed["packages"][pkg_id] = info.to_installed_dict()
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

        except Exception:
            # --- Roll back: restore the previous version (or clean up) -----
            # Best-effort: we swallow rollback errors so the original cause
            # still reaches the caller, but we log them for debugging.
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
            raise

        # --- Success: drop the backup --------------------------------------
        if backup_dir and os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)

    def uninstall_package(self, pkg_id):
        """Uninstall a package.

        If the package originated from a local My Tools registration that
        was later published (``source == "published"`` with a stored
        ``local_path``), the uninstall is treated as "revert to My Tools
        only": the registry-side env wiring is undone but the entry
        stays in installed.json with ``source = "local_script"`` so the
        user keeps their registration. Otherwise the entry is removed
        completely as before.
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

        # Demote published-from-local entries back to plain My Tools
        # registrations instead of dropping them. Registration state is
        # the user's data; uninstalling from a registry view shouldn't
        # erase it.
        if pkg_data.get("source") == "published" and pkg_data.get("local_path"):
            pkg_data["source"] = "local_script"
            pkg_data["activated_paths"] = {}
            pkg_data.pop("path", None)
            pkg_data.pop("sha256", None)
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

    def get_installed_version(self, pkg_id):
        """Return the installed version of the specified package."""
        pkg = self._installed.get("packages", {}).get(pkg_id)
        if pkg:
            return pkg.get("version")
        return None

    def is_installed(self, pkg_id):
        return pkg_id in self._installed.get("packages", {})
