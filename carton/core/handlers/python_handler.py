"""PythonPackageHandler — python_package type."""

import importlib
import os
import shutil
import sys

from carton.core.handlers.base import PackageHandler


class PythonPackageHandler(PackageHandler):

    def install(self, package_dir, meta, env_manager):
        env_manager.add_python_path(package_dir)

    def uninstall(self, package_dir, meta, env_manager):
        # Route through env_manager so the bookkeeping dict stays in sync
        # (direct sys.path.remove would leave a stale entry in the tracker
        # and later confuse cleanup_all / remove_tracked).
        env_manager.remove_python_path(package_dir)
        # Also remove from the module cache
        module_name = self._get_module(meta)
        to_remove = [k for k in sys.modules if k == module_name or k.startswith(module_name + ".")]
        for k in to_remove:
            del sys.modules[k]
        # Delete files
        if os.path.exists(package_dir):
            shutil.rmtree(package_dir)

    def activate(self, package_dir, meta, env_manager):
        env_manager.add_python_path(package_dir)

    def launch(self, meta):
        entry = meta.get("entry_point", {})
        module_name = entry.get("module", "")
        func_name = entry.get("function", "show")

        mod = importlib.import_module(module_name)
        func = getattr(mod, func_name)
        return func()

    def is_loaded(self, meta):
        module_name = self._get_module(meta)
        return module_name in sys.modules

    def _get_module(self, meta):
        entry = meta.get("entry_point", {})
        if isinstance(entry, dict):
            return entry.get("module", "")
        # Backward compatibility: "module:function" format
        if isinstance(entry, str) and ":" in entry:
            return entry.split(":")[0]
        return ""
