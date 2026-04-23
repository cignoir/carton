"""PluginHandler — plugin type."""

import os
import shutil

from carton.core.handlers.base import PackageHandler


class PluginHandler(PackageHandler):

    def install(self, package_dir, meta, env_manager):
        plugins_dir = self._get_plugins_dir(package_dir)
        if plugins_dir:
            env_manager.add_env_path("MAYA_PLUG_IN_PATH", plugins_dir)
        # Bundled scripts/ is wired to BOTH MAYA_SCRIPT_PATH (MEL source
        # resolution) AND sys.path (so ``import <pkg>`` works for Python
        # companions that the .mll's UI commands call into — a common
        # shape is a C++ plugin that registers menu items which then
        # invoke a Python Qt UI from the same repo's ``scripts/``).
        scripts_dir = os.path.join(package_dir, "scripts")
        if os.path.isdir(scripts_dir):
            env_manager.add_env_path("MAYA_SCRIPT_PATH", scripts_dir)
            env_manager.add_python_path(scripts_dir)

    def uninstall(self, package_dir, meta, env_manager):
        # Unload first
        entry = meta.get("entry_point", {})
        plugin_file = entry.get("plugin_file", "")
        if plugin_file:
            try:
                import maya.cmds
                if maya.cmds.pluginInfo(plugin_file, q=True, loaded=True):
                    maya.cmds.unloadPlugin(plugin_file)
            except (ImportError, RuntimeError):
                pass

        # Remove paths
        plugins_dir = self._get_plugins_dir(package_dir)
        if plugins_dir:
            env_manager.remove_env_path("MAYA_PLUG_IN_PATH", plugins_dir)
        scripts_dir = os.path.join(package_dir, "scripts")
        if os.path.isdir(scripts_dir):
            env_manager.remove_env_path("MAYA_SCRIPT_PATH", scripts_dir)
            env_manager.remove_python_path(scripts_dir)

        # Delete files
        if os.path.exists(package_dir):
            shutil.rmtree(package_dir)

    def activate(self, package_dir, meta, env_manager):
        plugins_dir = self._get_plugins_dir(package_dir)
        if plugins_dir:
            env_manager.add_env_path("MAYA_PLUG_IN_PATH", plugins_dir)
        scripts_dir = os.path.join(package_dir, "scripts")
        if os.path.isdir(scripts_dir):
            env_manager.add_env_path("MAYA_SCRIPT_PATH", scripts_dir)
            env_manager.add_python_path(scripts_dir)

        # Load if auto_load is specified
        entry = meta.get("entry_point", {})
        if entry.get("auto_load"):
            self._load_plugin(entry.get("plugin_file", ""))

    def launch(self, meta):
        entry = meta.get("entry_point", {})
        plugin_file = entry.get("plugin_file", "")
        ui_command = entry.get("ui_command", "")

        self._load_plugin(plugin_file)

        if ui_command:
            try:
                import maya.mel
                maya.mel.eval("{}()".format(ui_command))
            except ImportError:
                raise RuntimeError("Maya is not available")

    def is_loaded(self, meta):
        entry = meta.get("entry_point", {})
        plugin_file = entry.get("plugin_file", "")
        if not plugin_file:
            return False
        try:
            import maya.cmds
            return maya.cmds.pluginInfo(plugin_file, q=True, loaded=True)
        except (ImportError, RuntimeError):
            return False

    def _load_plugin(self, plugin_file):
        """Load the plugin."""
        if not plugin_file:
            return
        try:
            import maya.cmds
            if not maya.cmds.pluginInfo(plugin_file, q=True, loaded=True):
                maya.cmds.loadPlugin(plugin_file)
        except ImportError:
            raise RuntimeError("Maya is not available")

    def _get_plugins_dir(self, package_dir):
        """Return the path to the plug-ins/ subdirectory."""
        plugins = os.path.join(package_dir, "plug-ins")
        if os.path.isdir(plugins):
            return plugins
        return None
