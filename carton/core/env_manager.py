"""Centralized management of Maya environment variables."""

import os
import sys


class MayaEnvManager:
    """Centralized tracking and manipulation of Maya environment variables."""

    def __init__(self):
        self._added_paths = {}  # {"MAYA_SCRIPT_PATH": [path1, ...], ...}
        self._rehash_pending = False

    def add_python_path(self, path):
        """Add a path to sys.path."""
        if path not in sys.path:
            sys.path.insert(0, path)
            self._added_paths.setdefault("sys.path", []).append(path)

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
        """Remove a path from an environment variable."""
        current = os.environ.get(env_var, "")
        paths = current.split(os.pathsep) if current else []
        if path in paths:
            paths.remove(path)
            os.environ[env_var] = os.pathsep.join(paths)

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
        for env_var, paths in self._added_paths.items():
            for p in paths:
                if env_var == "sys.path":
                    if p in sys.path:
                        sys.path.remove(p)
                else:
                    self.remove_env_path(env_var, p)
        self._added_paths.clear()
