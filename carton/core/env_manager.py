"""Centralized management of Maya environment variables."""

import copy
import os
import sys


class MayaEnvManager:
    """Centralized tracking and manipulation of Maya environment variables.

    The manager keeps a bookkeeping dict of every path it has added so the
    matching remove can update both the live env var **and** the tracking
    list. Installer code uses :meth:`snapshot` / :meth:`diff_since` /
    :meth:`remove_tracked` to attribute adds to specific install operations
    for transactional uninstall.
    """

    def __init__(self):
        self._added_paths = {}  # {"MAYA_SCRIPT_PATH": [path1, ...], ...}
        self._rehash_pending = False

    def add_python_path(self, path):
        """Add a path to sys.path."""
        # Normalise so the dedup check survives mixed-separator entries
        # (Windows ``\\`` vs ``/``) coming from os.path.join shenanigans.
        path = os.path.normpath(path)
        if path not in sys.path:
            sys.path.insert(0, path)
            self._added_paths.setdefault("sys.path", []).append(path)
            # Drop the path importer cache so finders pick up the new
            # directory's contents on the next import attempt. Without
            # this, ``importlib.import_module`` returns "No module named"
            # for files that exist on disk in the freshly added path.
            import importlib
            importlib.invalidate_caches()

    def remove_python_path(self, path):
        """Remove a path from sys.path and drop it from the tracking book."""
        if path in sys.path:
            sys.path.remove(path)
        tracked = self._added_paths.get("sys.path")
        if tracked and path in tracked:
            tracked.remove(path)
            if not tracked:
                del self._added_paths["sys.path"]

    def add_env_path(self, env_var, path):
        """Add a path to an environment variable."""
        current = os.environ.get(env_var, "")
        paths = current.split(os.pathsep) if current else []
        if path not in paths:
            paths.insert(0, path)
            os.environ[env_var] = os.pathsep.join(paths)
            self._added_paths.setdefault(env_var, []).append(path)

        if env_var == "MAYA_SCRIPT_PATH":
            self._rehash_pending = True

    def remove_env_path(self, env_var, path):
        """Remove a path from an environment variable.

        Also drops the entry from the bookkeeping dict so
        :meth:`cleanup_all` does not later try to re-remove a path this
        manager no longer considers "added".
        """
        current = os.environ.get(env_var, "")
        paths = current.split(os.pathsep) if current else []
        if path in paths:
            paths.remove(path)
            os.environ[env_var] = os.pathsep.join(paths)
        tracked = self._added_paths.get(env_var)
        if tracked and path in tracked:
            tracked.remove(path)
            if not tracked:
                del self._added_paths[env_var]

    # -- transactional helpers used by InstallManager ----------------------

    def snapshot(self):
        """Return a deep copy of the current tracking dict.

        Call before ``handler.install(...)`` so the caller can later
        compute which env var entries the handler added.
        """
        return copy.deepcopy(self._added_paths)

    def diff_since(self, before):
        """Return the additions made since ``before`` was snapshot().

        Format: ``{env_var: [added_path, ...]}`` — same shape as
        ``_added_paths`` but containing only the new entries.
        """
        result = {}
        for env_var, after_list in self._added_paths.items():
            before_list = before.get(env_var, []) if before else []
            added = [p for p in after_list if p not in before_list]
            if added:
                result[env_var] = added
        return result

    def remove_tracked(self, tracked):
        """Remove every entry in ``tracked`` from its env var.

        Idempotent: paths that are already gone from ``os.environ`` /
        ``sys.path`` are silently skipped. Used on uninstall with the
        diff that was recorded during install, so we never miss a path
        the handler forgot to clean up.
        """
        if not tracked:
            return
        for env_var, paths in list(tracked.items()):
            for p in paths:
                if env_var == "sys.path":
                    self.remove_python_path(p)
                else:
                    self.remove_env_path(env_var, p)

    def flush(self):
        """Call after batch additions are complete. Runs rehash once if needed."""
        if self._rehash_pending:
            try:
                import maya.mel
                maya.mel.eval("rehash")
            except ImportError:
                pass  # When testing outside Maya
            self._rehash_pending = False

    def cleanup_all(self):
        """Remove all paths added by Carton on shutdown."""
        # Iterate over a snapshot so the in-loop mutations from
        # remove_env_path / remove_python_path don't invalidate the view.
        snapshot = {k: list(v) for k, v in self._added_paths.items()}
        for env_var, paths in snapshot.items():
            for p in paths:
                if env_var == "sys.path":
                    self.remove_python_path(p)
                else:
                    self.remove_env_path(env_var, p)
        self._added_paths.clear()
