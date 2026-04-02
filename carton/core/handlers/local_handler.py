"""LocalHandler — local type (local script integration)."""

import os

from carton.core.handlers.base import PackageHandler


class LocalHandler(PackageHandler):
    """Delegate local scripts based on their inner type."""

    def install(self, package_dir, meta, env_manager):
        # Local does not copy files. Symlink or path reference only
        local_path = meta.get("local_path", "")
        if not local_path or not os.path.exists(local_path):
            return

        link_dir = os.path.join(package_dir, "_local", meta.get("name", ""))
        try:
            os.makedirs(os.path.dirname(link_dir), exist_ok=True)
            if not os.path.exists(link_dir):
                os.symlink(local_path, link_dir, target_is_directory=True)
            meta["_link_mode"] = "symlink"
        except OSError:
            meta["_link_mode"] = "reference"

        self._activate_by_type(local_path, meta, env_manager)

    def uninstall(self, package_dir, meta, env_manager):
        local_path = meta.get("local_path", "")
        self._deactivate_by_type(local_path, meta, env_manager)

        # Remove symlink (do not touch original files)
        link_dir = os.path.join(package_dir, "_local", meta.get("name", ""))
        if os.path.islink(link_dir):
            os.unlink(link_dir)

    def activate(self, package_dir, meta, env_manager):
        local_path = meta.get("local_path", "")
        if not local_path:
            return
        if not os.path.exists(local_path):
            print("[Carton] Local path not found, skipping: {}".format(local_path))
            return
        self._activate_by_type(local_path, meta, env_manager)

    def launch(self, meta):
        """Delegate based on inner type."""
        inner_type = self._detect_inner_type(meta)
        entry = meta.get("entry_point", {})

        if inner_type == "python_package":
            from carton.core.handlers.python_handler import PythonPackageHandler
            PythonPackageHandler().launch(meta)
        elif inner_type == "mel_script":
            from carton.core.handlers.mel_handler import MelScriptHandler
            MelScriptHandler().launch(meta)
        elif inner_type == "plugin":
            from carton.core.handlers.plugin_handler import PluginHandler
            PluginHandler().launch(meta)

    def is_loaded(self, meta):
        inner_type = self._detect_inner_type(meta)
        if inner_type == "python_package":
            from carton.core.handlers.python_handler import PythonPackageHandler
            return PythonPackageHandler().is_loaded(meta)
        elif inner_type == "mel_script":
            from carton.core.handlers.mel_handler import MelScriptHandler
            return MelScriptHandler().is_loaded(meta)
        elif inner_type == "plugin":
            from carton.core.handlers.plugin_handler import PluginHandler
            return PluginHandler().is_loaded(meta)
        return False

    def _activate_by_type(self, local_path, meta, env_manager):
        """Add to environment variables based on inner type."""
        inner_type = self._detect_inner_type(meta)
        if inner_type == "python_package":
            env_manager.add_python_path(local_path)
        elif inner_type == "mel_script":
            scripts = os.path.join(local_path, "scripts")
            env_manager.add_env_path("MAYA_SCRIPT_PATH",
                                     scripts if os.path.isdir(scripts) else local_path)
        elif inner_type == "plugin":
            plugins = os.path.join(local_path, "plug-ins")
            if os.path.isdir(plugins):
                env_manager.add_env_path("MAYA_PLUG_IN_PATH", plugins)
            scripts = os.path.join(local_path, "scripts")
            if os.path.isdir(scripts):
                env_manager.add_env_path("MAYA_SCRIPT_PATH", scripts)

    def _deactivate_by_type(self, local_path, meta, env_manager):
        """Remove from environment variables based on inner type."""
        inner_type = self._detect_inner_type(meta)
        if inner_type == "python_package":
            import sys
            if local_path in sys.path:
                sys.path.remove(local_path)
        elif inner_type == "mel_script":
            scripts = os.path.join(local_path, "scripts")
            env_manager.remove_env_path("MAYA_SCRIPT_PATH",
                                        scripts if os.path.isdir(scripts) else local_path)
        elif inner_type == "plugin":
            plugins = os.path.join(local_path, "plug-ins")
            if os.path.isdir(plugins):
                env_manager.remove_env_path("MAYA_PLUG_IN_PATH", plugins)

    def _detect_inner_type(self, meta):
        """Determine the inner type from the entry_point's type field."""
        entry = meta.get("entry_point", {})
        if isinstance(entry, dict):
            return {
                "python": "python_package",
                "mel": "mel_script",
                "plugin": "plugin",
            }.get(entry.get("type", ""), "python_package")
        return "python_package"
