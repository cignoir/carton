"""MelScriptHandler — mel_script type."""

import os
import shutil

from carton.core.handlers.base import PackageHandler


class MelScriptHandler(PackageHandler):

    def install(self, package_dir, meta, env_manager):
        scripts_dir = self._get_scripts_dir(package_dir)
        if scripts_dir:
            env_manager.add_env_path("MAYA_SCRIPT_PATH", scripts_dir)

    def uninstall(self, package_dir, meta, env_manager):
        scripts_dir = self._get_scripts_dir(package_dir)
        if scripts_dir:
            env_manager.remove_env_path("MAYA_SCRIPT_PATH", scripts_dir)
        # rehash
        try:
            import maya.mel
            maya.mel.eval("rehash")
        except ImportError:
            pass
        # Delete files
        if os.path.exists(package_dir):
            shutil.rmtree(package_dir)

    def activate(self, package_dir, meta, env_manager):
        scripts_dir = self._get_scripts_dir(package_dir)
        if scripts_dir:
            env_manager.add_env_path("MAYA_SCRIPT_PATH", scripts_dir)

    def launch(self, meta):
        entry = meta.get("entry_point", {})
        script = entry.get("script", "")
        procedure = entry.get("procedure", "")
        if not script or not procedure:
            raise RuntimeError("MEL entry_point missing script or procedure")
        try:
            import maya.mel
            maya.mel.eval('source "{}"; {}();'.format(script, procedure))
        except ImportError:
            raise RuntimeError("Maya is not available")

    def is_loaded(self, meta):
        entry = meta.get("entry_point", {})
        procedure = entry.get("procedure", "")
        if not procedure:
            return False
        try:
            import maya.mel
            return bool(maya.mel.eval('exists "{}"'.format(procedure)))
        except ImportError:
            return False

    def _get_scripts_dir(self, package_dir):
        """Return the path to the scripts/ subdirectory, or package_dir itself if not found."""
        scripts = os.path.join(package_dir, "scripts")
        if os.path.isdir(scripts):
            return scripts
        return package_dir
