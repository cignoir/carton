"""Registration and management of local scripts/packages (reference-based)."""

import json
import os
from datetime import datetime, timezone

from carton.core.identity import normalize
from carton.core.path_utils import resolve_local_path, store_local_path


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
                 author="", namespace="", home_origin=None,
                 include_compiled=False):
        """Register locally.

        Args:
            file_path: File path or folder path (held as a reference)
            name: Module name / script name (required)
            display_name: Display name in the UI
            icon: Emoji or image path
            description: Description
            pkg_type: "python_package" or "mel_script"
            entry_point: Entry point dict
            is_folder: Whether this is a folder registration
            namespace: Optional namespace. Required to publish; may be empty
                for personal-only registration.
            home_origin: Optional v5.0 home origin payload (embedded /
                github / url / local variant dict).

        Returns:
            pkg_id: ``"<namespace>/<name>"`` if namespace is set, else ``name``.
        """
        name = normalize(name)
        if not name:
            raise ValueError("name is required to register a script")
        ns = normalize(namespace)
        pkg_id = "{}/{}".format(ns, name) if ns else name

        # Env wiring uses the absolute path that the UI handed us.
        self._add_to_env(file_path, pkg_type, is_folder)

        # ...but the path we persist collapses the user's home to ``~`` so
        # the entry survives a home-dir rename or being synced to another
        # machine with the same tool layout.
        stored_path = store_local_path(file_path)

        # Record in installed.json
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        installed_data = {
            "namespace": ns,
            "name": name,
            "display_name": display_name,
            "version": version,
            "author": author,
            "type": pkg_type,
            "installed_at": now,
            "entry_point": entry_point,
            "source": "local",
            "local_path": stored_path,
            "is_folder": is_folder,
            "icon": icon,
            "description": description,
        }
        if home_origin:
            installed_data["home_origin"] = home_origin
        if include_compiled:
            installed_data["include_compiled"] = True

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

        local_path = resolve_local_path(pkg_data.get("local_path", ""))
        is_folder = pkg_data.get("is_folder", False)
        pkg_type = pkg_data.get("type", "")

        self._remove_from_env(local_path, pkg_type, is_folder)

        del installed["packages"][pkg_id]
        self._install_mgr._save_installed()

    def activate(self, pkg_id):
        """Activate a My Tools entry at Maya startup.

        Activates both pure My Tools (``source="local"``) and double-bound
        registry installs (``source="registry"`` with ``local_path``) so the
        original source path keeps participating in import resolution.
        """
        from carton.core.install_state import is_my_tools

        installed = self._install_mgr._installed
        pkg_data = installed["packages"].get(pkg_id)
        if not pkg_data or not is_my_tools(pkg_data):
            return

        local_path = resolve_local_path(pkg_data.get("local_path", ""))
        if not local_path or not os.path.exists(local_path):
            print("[Carton] Local path not found: {}".format(local_path))
            return

        is_folder = pkg_data.get("is_folder", False)
        pkg_type = pkg_data.get("type", "")
        self._add_to_env(local_path, pkg_type, is_folder)

    def launch(self, pkg_data):
        """Launch a local script."""
        entry = pkg_data.get("entry_point", {}) or {}
        ep_type = entry.get("type", "")

        # Resolve the portable stored path once, then pass the expanded
        # version into pkg_data so downstream branches (and the delegated
        # maya_module handler) work with an absolute path.
        stored = pkg_data.get("local_path", "")
        resolved = resolve_local_path(stored)
        if stored and resolved != stored:
            pkg_data = dict(pkg_data)
            pkg_data["local_path"] = resolved

        # Maya modules: delegate to the dedicated handler so the same logic
        # (free-form command, structured python entry, or userSetup re-exec)
        # runs for both locally-registered and installed-from-registry modules.
        if pkg_data.get("type") == "maya_module":
            from carton.core.handlers.maya_module_handler import MayaModuleHandler
            MayaModuleHandler().launch(pkg_data)
            return

        if not ep_type:
            # No recognised entry_point shape — usually a legacy / malformed
            # ``package.json`` whose ``entry_point`` was adopted verbatim at
            # register time (EditDialog rewrites it into a valid shape, which
            # is why editing + saving makes the tool launch).
            hint = self._describe_entry_for_error(entry)
            raise RuntimeError(
                "Cannot launch: entry_point has no usable 'type' field. "
                "Got {}. Open Edit and save to rebuild it.".format(hint)
            )

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
            import sys as _sys
            # Ensure the package path is in sys.path before importing
            local_path = pkg_data.get("local_path", "")
            if local_path and os.path.exists(local_path):
                self._add_to_env(local_path, pkg_data.get("type", ""),
                                 pkg_data.get("is_folder", False))
            # Always drop the path importer cache before resolving — the
            # path may have been added in a previous session (skipping
            # add_python_path's own invalidate) and the cache built since
            # then doesn't know about its contents.
            importlib.invalidate_caches()
            module_name = entry.get("module", "")
            func_name = entry.get("function", "show")
            # Drop any negative-cache entry from a previous failed import
            # so the next attempt actually re-resolves through the path
            # importers. ``sys.modules[name] = None`` is how Python marks
            # "this name has already been tried and was not found".
            if module_name in _sys.modules and _sys.modules[module_name] is None:
                del _sys.modules[module_name]
            mod = importlib.import_module(module_name)
            func = getattr(mod, func_name)
            func()
        else:
            raise RuntimeError(
                "Cannot launch: unknown entry_point type {!r}".format(ep_type)
            )

    @staticmethod
    def _describe_entry_for_error(entry):
        """Compact description of a malformed entry_point for error messages."""
        if not isinstance(entry, dict):
            return repr(entry)
        if not entry:
            return "{}"
        keys = ", ".join(sorted(entry.keys()))
        return "{{{}}}".format(keys)

    def _add_to_env(self, path, pkg_type, is_folder):
        """Add a path to Maya environment variables."""
        if pkg_type == "maya_module" and is_folder:
            # Delegate to the maya_module handler so locally-registered modules
            # use the exact same env wiring as installed-from-registry ones.
            from carton.core.handlers.maya_module_handler import (
                resolve_paths, _apply_paths, _exec_user_setup,
                _ACTIVATED_DIRS,
            )
            paths = resolve_paths(path)
            _apply_paths(self._env_mgr, paths)
            key = os.path.normpath(path)
            if "user_setup" in paths and key not in _ACTIVATED_DIRS:
                _exec_user_setup(paths["user_setup"])
                _ACTIVATED_DIRS.add(key)
            return
        if is_folder:
            # Folder: add the right directory(ies) to sys.path so the
            # user can either ``import folder_name`` (treat folder as a
            # package) or ``import some_module`` for a standalone .py
            # sitting inside it. When ``__init__.py`` exists we add BOTH
            # the parent (enables ``import folder_name``) and the folder
            # itself (enables ``import sibling_module``); without one we
            # only need the folder itself.
            init_py = os.path.join(path, "__init__.py")
            targets = []
            if os.path.exists(init_py):
                targets.append(os.path.dirname(path))
                targets.append(path)
            else:
                targets.append(path)
            if pkg_type == "python_package":
                # Use bulk extend so the activation order of ``targets``
                # is preserved on sys.path (loop+insert(0) would reverse it).
                self._env_mgr.extend_python_path(targets)
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
        if pkg_type == "maya_module" and is_folder:
            from carton.core.handlers.maya_module_handler import (
                resolve_paths, _remove_paths, _ACTIVATED_DIRS,
            )
            _remove_paths(self._env_mgr, resolve_paths(path))
            _ACTIVATED_DIRS.discard(os.path.normpath(path))
            return
        if is_folder:
            init_py = os.path.join(path, "__init__.py")
            target = os.path.dirname(path) if os.path.exists(init_py) else path
            if pkg_type == "python_package":
                self._env_mgr.remove_python_path(target)
            elif pkg_type == "mel_script":
                scripts_dir = os.path.join(path, "scripts")
                self._env_mgr.remove_env_path("MAYA_SCRIPT_PATH",
                                              scripts_dir if os.path.isdir(scripts_dir) else path)
        else:
            script_dir = os.path.dirname(path)
            if pkg_type == "plugin":
                self._env_mgr.remove_env_path("MAYA_PLUG_IN_PATH", script_dir)
            elif pkg_type == "python_package":
                self._env_mgr.remove_python_path(script_dir)
            elif pkg_type == "mel_script":
                self._env_mgr.remove_env_path("MAYA_SCRIPT_PATH", script_dir)
