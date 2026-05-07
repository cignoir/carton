"""Registration and management of local scripts/packages (reference-based)."""

import json
import os
from datetime import datetime, timezone

from carton.core.identity import normalize
from carton.core.install_state import is_my_tools
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
        catalogue installs (``source="registry"`` with ``local_path``) so
        the original source path keeps participating in import resolution.
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
        # runs for both locally-registered and installed-from-catalogue modules.
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
            # Maya binary plugin (.mll). Two concrete shapes arrive here:
            #   * single-file registration → ``file`` carries the basename,
            #     ``local_path`` is the .mll itself
            #   * folder package.json registration → ``plugin_file`` carries
            #     the extension-less plugin name, ``local_path`` is the
            #     package folder (with a ``plug-ins/`` subdir that's already
            #     on MAYA_PLUG_IN_PATH via _add_to_env)
            import maya.cmds
            local_path = pkg_data.get("local_path", "")
            plugin_file = entry.get("plugin_file") or entry.get("file", "")
            is_folder = pkg_data.get("is_folder", False)
            if is_folder:
                # MAYA_PLUG_IN_PATH has ``plug-ins/`` wired up already —
                # let Maya resolve the bare name.
                plugin_path = plugin_file
            elif local_path and os.path.isfile(local_path):
                plugin_path = local_path
            elif local_path and os.path.isdir(local_path):
                plugin_path = os.path.join(local_path, plugin_file)
            else:
                plugin_path = plugin_file
            if not maya.cmds.pluginInfo(plugin_path, q=True, loaded=True):
                maya.cmds.loadPlugin(plugin_path)
            # Optional: run a command after loading (e.g. to open the UI).
            # ``command`` — legacy single-file shape (raw Python exec).
            # ``ui_command`` — package.json shape (MEL procedure name).
            command = entry.get("command", "")
            if command:
                import __main__
                exec(command, __main__.__dict__)
            ui_command = entry.get("ui_command", "")
            if ui_command:
                import maya.mel
                maya.mel.eval("{}()".format(ui_command))
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
            # Dev reload: for My Tools packages, evict the cached module
            # tree so the next import re-reads the source. Lets authors
            # iterate without restarting Maya. Existing top-level widgets
            # whose class came from this module are closed first to avoid
            # leaving zombie workspaceControls when the new show() builds
            # a fresh window. Catalogue-installed packages skip this so
            # ordinary users keep the cached-import speed.
            if (module_name
                    and self._dev_reload_enabled()
                    and is_my_tools(pkg_data)
                    and module_name in _sys.modules):
                _close_widgets_from_module(module_name)
                stale = [
                    k for k in list(_sys.modules)
                    if k == module_name or k.startswith(module_name + ".")
                ]
                for k in stale:
                    del _sys.modules[k]
            mod = importlib.import_module(module_name)
            self._apply_tool_language(mod)
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

    def _dev_reload_enabled(self):
        """Whether to evict cached My Tools modules on launch.

        ``getattr(None, ..., False)`` covers the ``config=None`` case used in
        unit tests so legacy launch tests keep their cached-import semantics.
        """
        return bool(getattr(self._config, "dev_reload_my_tools", False))

    def _apply_tool_language(self, mod):
        """Sync the tool's UI language to Carton's active language.

        Two channels, both best-effort and tolerant of failure:

        * ``CARTON_LANGUAGE`` environment variable — set unconditionally
          so tools that don't implement the ``set_language`` hook can
          still pick up the active language at startup (or pass it on
          to their own subprocess workers).
        * ``mod.set_language(code)`` — the explicit hook. If the tool's
          top-level package exposes the function, we call it with the
          resolved code. ``carton.tool_i18n`` provides a re-exportable
          ``set_language`` so the contract is satisfied by a single
          import in the tool's ``__init__.py``.

        Failures are swallowed: a faulty translator must not prevent the
        tool from launching.
        """
        try:
            from carton.ui.i18n import get_language
            lang = get_language() or "en"
        except ImportError:
            lang = "en"

        # Make the env var visible to anything the tool spawns later.
        os.environ["CARTON_LANGUAGE"] = lang

        hook = getattr(mod, "set_language", None)
        if not callable(hook):
            return
        try:
            hook(lang)
        except Exception:
            # A bug in the tool's i18n wiring shouldn't block launch.
            # The tool will simply render in whatever language it
            # defaulted to.
            pass

    def _add_to_env(self, path, pkg_type, is_folder):
        """Add a path to Maya environment variables."""
        if pkg_type == "maya_module" and is_folder:
            # Delegate to the maya_module handler so locally-registered modules
            # use the exact same env wiring as installed-from-catalogue ones.
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
            elif pkg_type == "plugin":
                # Folder plugin: mirror PluginHandler.install — plug-ins/
                # goes on MAYA_PLUG_IN_PATH, optional scripts/ goes on
                # MAYA_SCRIPT_PATH *and* sys.path so Python companions
                # bundled alongside the .mll can be imported by the
                # plugin's own UI commands.
                plugins_dir = os.path.join(path, "plug-ins")
                if os.path.isdir(plugins_dir):
                    self._env_mgr.add_env_path("MAYA_PLUG_IN_PATH", plugins_dir)
                scripts_dir = os.path.join(path, "scripts")
                if os.path.isdir(scripts_dir):
                    self._env_mgr.add_env_path("MAYA_SCRIPT_PATH", scripts_dir)
                    self._env_mgr.add_python_path(scripts_dir)
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
            elif pkg_type == "plugin":
                plugins_dir = os.path.join(path, "plug-ins")
                if os.path.isdir(plugins_dir):
                    self._env_mgr.remove_env_path("MAYA_PLUG_IN_PATH", plugins_dir)
                scripts_dir = os.path.join(path, "scripts")
                if os.path.isdir(scripts_dir):
                    self._env_mgr.remove_env_path("MAYA_SCRIPT_PATH", scripts_dir)
                    self._env_mgr.remove_python_path(scripts_dir)
        else:
            script_dir = os.path.dirname(path)
            if pkg_type == "plugin":
                self._env_mgr.remove_env_path("MAYA_PLUG_IN_PATH", script_dir)
            elif pkg_type == "python_package":
                self._env_mgr.remove_python_path(script_dir)
            elif pkg_type == "mel_script":
                self._env_mgr.remove_env_path("MAYA_SCRIPT_PATH", script_dir)


def _close_widgets_from_module(module_name):
    """Synchronously destroy every QWidget whose class came from
    ``module_name`` (or a submodule), tearing down any wrapping Maya
    workspaceControl first.

    Why so aggressive: the obvious ``close() + deleteLater()`` was leaving
    orphans alive after dev-reload. When Maya's ``deleteUI`` tears down a
    workspaceControl, Qt re-parents the inner widget to None and restores
    its ``Qt.Window`` flag — turning what was a docked panel into a
    free-floating top-level. ``close()`` on that orphan is unreliable
    (the close event ordering loses to Maya's tear-down) and
    ``deleteLater()`` is async, so the new widget gets created and shown
    before the old orphan vanishes — and the user sees both at once.

    Strategy:
        1. Filter to top-level / window-flagged widgets only — child
           widgets are destroyed automatically when their parent dies, and
           operating on them individually creates ordering hazards (a
           child's parent might be invalid by the time we reach it).
        2. For each target, delete its workspaceControl wrapper while it's
           still parented in (``_delete_dockable_wrapper`` detaches first).
        3. Call ``close()`` so the widget's ``closeEvent`` fires — that's
           where well-behaved tools disconnect signals and kill Maya
           scriptJobs. ``shiboken.delete`` skips closeEvent, so calling
           ``close()`` first prevents callback leaks.
        4. Synchronously ``shiboken.delete()`` the C++ object so the
           orphan is GONE before control returns to the caller. Falls
           back to ``deleteLater()`` if shiboken can't import.

    Skipped silently when Qt isn't importable (CLI / headless tests) or
    when no QApplication exists yet.

    The ``except RuntimeError`` here catches Qt's "already deleted" error,
    which happens naturally when one widget's destruction tears down a
    child that's later in our list. That's tear-down race, not a
    swallowed bug.
    """
    try:
        from carton.ui.compat import QtWidgets
    except ImportError:
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        return

    try:
        from shiboken6 import delete as _delete  # type: ignore[import-not-found]
    except ImportError:
        try:
            from shiboken2 import delete as _delete  # type: ignore[import-not-found]
        except ImportError:
            _delete = None  # type: ignore[assignment]

    targets = []
    seen = set()
    for w in app.allWidgets():
        if id(w) in seen:
            continue
        seen.add(id(w))
        klass = type(w)
        mod = getattr(klass, "__module__", "") or ""
        if mod != module_name and not mod.startswith(module_name + "."):
            continue
        # Only act on top-level / window widgets — children are destroyed
        # transitively when their parent goes away.
        try:
            is_root = w.isWindow() or w.parent() is None
        except RuntimeError:
            continue
        if is_root:
            targets.append(w)

    for w in targets:
        _delete_dockable_wrapper(w)
        # close() first so closeEvent fires and the widget can run its own
        # teardown — disconnect signals, kill Maya scriptJobs, drop event
        # filters. ``shiboken.delete`` skips closeEvent entirely, so without
        # this any tool that relied on closeEvent for cleanup would leak
        # callbacks (e.g. a SceneSaved scriptJob that fires later and
        # touches the now-deleted Qt objects). Each call is independent
        # best-effort: a widget that ``ignore``s its close event still
        # gets reached by the destruction step below.
        try:
            w.close()
        except RuntimeError:
            pass
        try:
            w.hide()
        except RuntimeError:
            pass
        try:
            if _delete is not None:
                _delete(w)
            else:
                w.deleteLater()
        except RuntimeError:
            pass


def _delete_dockable_wrapper(widget):
    """Delete the Maya workspaceControl that wraps this widget, if any.

    ``MayaQWidgetDockableMixin.show(dockable=True)`` creates a control named
    ``<objectName>WorkspaceControl`` and registers it with Maya. The control
    survives ``QWidget.close()`` — Maya keeps the dock slot around so a
    subsequent ``show()`` can re-attach the widget. That's exactly what we
    don't want during a dev reload.

    Three-step teardown:

      1. ``setParent(None)`` + ``hide()`` on the widget so it's detached
         from the dock and explicitly hidden BEFORE ``deleteUI`` runs —
         otherwise Maya's tear-down silently re-orphans the widget back
         into a visible top-level (Qt.Window flag restoration), and our
         caller's destruction races against it.
      2. ``cmds.workspaceControl(..., e=True, close=True)`` — required on
         some Maya versions before ``deleteUI`` actually destroys the C++
         wrapper instead of just retaining it.
      3. ``cmds.deleteUI`` to remove the named control.

    Each call is independently best-effort: if one is rejected (older
    Maya, race with Qt tear-down), we still try the next.
    """
    try:
        name = widget.objectName()
    except RuntimeError:
        return
    if not name:
        return
    try:
        import maya.cmds as cmds  # type: ignore[import-not-found]
    except ImportError:
        return
    ctl = name + "WorkspaceControl"
    if not cmds.workspaceControl(ctl, exists=True):
        return
    # Detach + hide BEFORE Maya tears the dock down — orphaning the widget
    # via deleteUI would otherwise make it a visible top-level.
    try:
        widget.setParent(None)
        widget.hide()
    except RuntimeError:
        pass
    try:
        cmds.workspaceControl(ctl, edit=True, close=True)
    except (RuntimeError, TypeError):
        pass
    try:
        cmds.deleteUI(ctl)
    except RuntimeError:
        pass
