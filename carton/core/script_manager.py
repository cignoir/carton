"""Registration and management of local scripts/packages (reference-based)."""

import json
import os
import uuid as _uuid
from datetime import datetime, timezone


class ScriptManager:
    """Register and manage local files/folders in Carton.

    Holds references to the original files without copying.
    Edits are made to the original files and take effect at the next Maya startup.
    """

    def __init__(self, config, install_manager, env_manager):
        self._config = config
        self._install_mgr = install_manager
        self._env_mgr = env_manager

    def register(self, file_path, name, display_name, icon, description,
                 pkg_type, entry_point, is_folder=False, version="0.0.0",
                 author="", pkg_id=None):
        """Register locally.

        Args:
            file_path: File path or folder path (held as a reference)
            name: Module name / script name
            display_name: Display name in the UI
            icon: Emoji or image path
            description: Description
            pkg_type: "python_package" or "mel_script"
            entry_point: Entry point dict
            is_folder: Whether this is a folder registration
            pkg_id: Reuse an existing UUID (from package.json) if provided

        Returns:
            pkg_id (UUID)
        """
        if not pkg_id:
            pkg_id = str(_uuid.uuid4())

        # Add to environment variables (reference-based)
        self._add_to_env(file_path, pkg_type, is_folder)

        # Record in installed.json
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        installed_data = {
            "name": name,
            "display_name": display_name,
            "version": version,
            "author": author,
            "type": pkg_type,
            "installed_at": now,
            "entry_point": entry_point,
            "path": "",
            "source": "local_script",
            "local_path": file_path,
            "is_folder": is_folder,
            "icon": icon,
            "description": description,
        }

        installed = self._install_mgr._installed
        installed["packages"][pkg_id] = installed_data
        self._install_mgr._save_installed()

        return pkg_id

    def unregister(self, pkg_id):
        """Unregister. Does not touch the original files."""
        installed = self._install_mgr._installed
        pkg_data = installed["packages"].get(pkg_id)
        if not pkg_data:
            return

        local_path = pkg_data.get("local_path", "")
        is_folder = pkg_data.get("is_folder", False)
        pkg_type = pkg_data.get("type", "")

        self._remove_from_env(local_path, pkg_type, is_folder)

        del installed["packages"][pkg_id]
        self._install_mgr._save_installed()

    def activate(self, pkg_id):
        """Activate a script at Maya startup."""
        installed = self._install_mgr._installed
        pkg_data = installed["packages"].get(pkg_id)
        if not pkg_data or pkg_data.get("source") != "local_script":
            return

        local_path = pkg_data.get("local_path", "")
        if not local_path or not os.path.exists(local_path):
            print("[Carton] Local path not found: {}".format(local_path))
            return

        is_folder = pkg_data.get("is_folder", False)
        pkg_type = pkg_data.get("type", "")
        self._add_to_env(local_path, pkg_type, is_folder)

    def launch(self, pkg_data):
        """Launch a local script."""
        entry = pkg_data.get("entry_point", {})
        ep_type = entry.get("type", "")

        if ep_type == "plugin":
            # Maya binary plugin (.mll)
            import maya.cmds
            local_path = pkg_data.get("local_path", "")
            plugin_file = entry.get("file", "")
            if local_path and os.path.isfile(local_path):
                plugin_path = local_path
            elif local_path and os.path.isdir(local_path):
                plugin_path = os.path.join(local_path, plugin_file)
            else:
                plugin_path = plugin_file
            if not maya.cmds.pluginInfo(plugin_path, q=True, loaded=True):
                maya.cmds.loadPlugin(plugin_path)
            # Optional: run a command after loading (e.g. to open the UI)
            command = entry.get("command", "")
            if command:
                import __main__
                exec(command, __main__.__dict__)
        elif ep_type == "exec":
            # Top-level execution
            local_path = pkg_data.get("local_path", "")
            if not local_path or not os.path.exists(local_path):
                raise RuntimeError("Script not found: {}".format(local_path))
            if local_path.endswith(".mll"):
                # Legacy: .mll registered as exec before plugin type existed
                import maya.cmds
                if not maya.cmds.pluginInfo(local_path, q=True, loaded=True):
                    maya.cmds.loadPlugin(local_path)
            elif local_path.endswith(".mel"):
                import maya.mel
                maya.mel.eval('source "{}"'.format(local_path.replace("\\", "/")))
            else:
                import __main__
                with open(local_path, "r", encoding="utf-8") as f:
                    exec(compile(f.read(), local_path, "exec"), __main__.__dict__)
        elif ep_type == "mel":
            import maya.mel
            script = entry.get("script", "")
            procedure = entry.get("procedure", "")
            maya.mel.eval('source "{}"; {}();'.format(script, procedure))
        elif ep_type == "python":
            import importlib
            # Ensure the package path is in sys.path before importing
            local_path = pkg_data.get("local_path", "")
            if local_path and os.path.exists(local_path):
                self._add_to_env(local_path, pkg_data.get("type", ""),
                                 pkg_data.get("is_folder", False))
            module_name = entry.get("module", "")
            func_name = entry.get("function", "show")
            mod = importlib.import_module(module_name)
            func = getattr(mod, func_name)
            func()

    def _add_to_env(self, path, pkg_type, is_folder):
        """Add a path to Maya environment variables."""
        if is_folder:
            # Folder: add parent directory to sys.path (to enable import folder_name)
            parent = os.path.dirname(path) if os.path.basename(path) != "" else path
            # Check if the folder itself (with package.json) is an import target
            init_py = os.path.join(path, "__init__.py")
            if os.path.exists(init_py):
                # path is my_tool/ and my_tool/__init__.py exists
                # -> Add parent directory to enable import my_tool
                target = os.path.dirname(path)
            else:
                # Module folder exists inside path
                target = path
            if pkg_type == "python_package":
                self._env_mgr.add_python_path(target)
            elif pkg_type == "mel_script":
                scripts_dir = os.path.join(path, "scripts")
                self._env_mgr.add_env_path("MAYA_SCRIPT_PATH",
                                           scripts_dir if os.path.isdir(scripts_dir) else path)
        else:
            # File: add the file's directory
            script_dir = os.path.dirname(path)
            if pkg_type == "plugin":
                self._env_mgr.add_env_path("MAYA_PLUG_IN_PATH", script_dir)
            elif pkg_type == "python_package":
                self._env_mgr.add_python_path(script_dir)
            elif pkg_type == "mel_script":
                self._env_mgr.add_env_path("MAYA_SCRIPT_PATH", script_dir)

    def _remove_from_env(self, path, pkg_type, is_folder):
        """Remove a path from Maya environment variables."""
        import sys
        if is_folder:
            init_py = os.path.join(path, "__init__.py")
            target = os.path.dirname(path) if os.path.exists(init_py) else path
            if pkg_type == "python_package":
                if target in sys.path:
                    sys.path.remove(target)
            elif pkg_type == "mel_script":
                scripts_dir = os.path.join(path, "scripts")
                self._env_mgr.remove_env_path("MAYA_SCRIPT_PATH",
                                              scripts_dir if os.path.isdir(scripts_dir) else path)
        else:
            script_dir = os.path.dirname(path)
            if pkg_type == "plugin":
                self._env_mgr.remove_env_path("MAYA_PLUG_IN_PATH", script_dir)
            elif pkg_type == "python_package":
                if script_dir in sys.path:
                    sys.path.remove(script_dir)
            elif pkg_type == "mel_script":
                self._env_mgr.remove_env_path("MAYA_SCRIPT_PATH", script_dir)
