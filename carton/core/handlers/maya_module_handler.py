"""MayaModuleHandler — Autodesk Application Package / Maya module type.

A Maya module folder bundles scripts (Python + MEL), plugins, icons, and an
optional ``userSetup.py`` that registers menus or shelves at Maya startup.
Carton wires up the right env vars and exec's ``userSetup.py`` deferred so
the module behaves the same as if Maya had loaded it via its native
``MAYA_MODULE_PATH`` mechanism.

Activation is idempotent within a single process: a module-level set tracks
which folders have already had ``userSetup.py`` executed, so calling
``activate`` (or clicking the "Activate" button) twice doesn't double-register
menus.
"""

import importlib
import os
import shutil

from carton.core.handlers.base import PackageHandler
from carton.core.maya_module_detect import (
    find_module_files,
    parse_mod_file,
    parse_package_contents,
)


# Process-wide set of package_dir paths whose userSetup.py has been executed
# this session. Cleared on Maya restart.
_ACTIVATED_DIRS = set()

_PLUGIN_EXTS = (".mll", ".py", ".so", ".bundle")


def resolve_paths(package_dir):
    """Discover the standard subdirectories of a Maya module folder.

    Returns a dict with the following keys (any of which may be missing):

    - ``scripts``: directory to add to sys.path AND MAYA_SCRIPT_PATH
    - ``plug_in_dirs``: list of directories containing native plug-ins
    - ``icons``: directory to add to XBMLANGPATH
    - ``presets``: directory to add to MAYA_PRESET_PATH
    - ``user_setup``: absolute path to userSetup.py (if present)

    Tries the ``Contents/`` layout first, then the bare layout, then any
    overrides from a ``.mod`` file at the folder root.
    """
    out = {}
    if not package_dir or not os.path.isdir(package_dir):
        return out

    # Pick a base directory for "scripts" / "plug-ins" lookups. Application
    # Package style nests these under Contents/.
    contents = os.path.join(package_dir, "Contents")
    base = contents if os.path.isdir(contents) else package_dir

    candidates = {
        "scripts": ["scripts"],
        "icons": ["icons"],
        "presets": ["presets"],
    }
    for key, names in candidates.items():
        for n in names:
            p = os.path.join(base, n)
            if os.path.isdir(p):
                out[key] = p
                break

    # Plug-in dirs: Maya's plugin path is non-recursive, so walk one level
    # deep and collect every directory that actually holds a plugin file.
    plug_root = os.path.join(base, "plug-ins")
    if os.path.isdir(plug_root):
        plug_dirs = []
        if _has_plugin_files(plug_root):
            plug_dirs.append(plug_root)
        for sub in _iter_subdirs(plug_root, max_depth=3):
            if _has_plugin_files(sub):
                plug_dirs.append(sub)
        if plug_dirs:
            out["plug_in_dirs"] = plug_dirs

    # userSetup.py
    if "scripts" in out:
        us = os.path.join(out["scripts"], "userSetup.py")
        if os.path.isfile(us):
            out["user_setup"] = us

    # PackageContents.xml may name a different ComponentEntry
    pkg_contents, mod_files = find_module_files(package_dir)
    if pkg_contents and "user_setup" not in out:
        parsed = parse_package_contents(pkg_contents)
        rel = parsed.get("user_setup")
        if rel:
            candidate = os.path.join(package_dir, rel)
            if os.path.isfile(candidate):
                out["user_setup"] = candidate

    # .mod overrides win when present
    if mod_files:
        mod = parse_mod_file(mod_files[0])
        for key in ("scripts", "icons", "presets"):
            if key in mod:
                p = os.path.join(package_dir, mod[key])
                if os.path.isdir(p):
                    out[key] = p
        if "plug_ins" in mod:
            p = os.path.join(package_dir, mod["plug_ins"])
            if os.path.isdir(p):
                # Replace whatever we discovered earlier
                if _has_plugin_files(p):
                    out["plug_in_dirs"] = [p]
                else:
                    out["plug_in_dirs"] = [
                        sub for sub in _iter_subdirs(p, max_depth=3)
                        if _has_plugin_files(sub)
                    ]

    return out


def _iter_subdirs(root, max_depth=3):
    """Yield subdirectories of ``root`` up to ``max_depth`` levels deep."""
    root = os.path.normpath(root)
    base_depth = root.count(os.sep)
    for current, dirs, _files in os.walk(root):
        depth = current.count(os.sep) - base_depth
        if depth >= max_depth:
            dirs[:] = []
            continue
        for d in dirs:
            yield os.path.join(current, d)


def _has_plugin_files(path):
    try:
        for entry in os.listdir(path):
            full = os.path.join(path, entry)
            if os.path.isfile(full) and entry.lower().endswith(_PLUGIN_EXTS):
                return True
    except OSError:
        return False
    return False


def _apply_paths(env_manager, paths):
    """Add resolved paths to the Maya environment via env_manager."""
    if "scripts" in paths:
        env_manager.add_python_path(paths["scripts"])
        env_manager.add_env_path("MAYA_SCRIPT_PATH", paths["scripts"])
    for d in paths.get("plug_in_dirs", []):
        env_manager.add_env_path("MAYA_PLUG_IN_PATH", d)
    if "icons" in paths:
        env_manager.add_env_path("XBMLANGPATH", paths["icons"])
    if "presets" in paths:
        env_manager.add_env_path("MAYA_PRESET_PATH", paths["presets"])


def _remove_paths(env_manager, paths):
    """Reverse of :func:`_apply_paths`."""
    import sys as _sys
    if "scripts" in paths:
        if paths["scripts"] in _sys.path:
            _sys.path.remove(paths["scripts"])
        env_manager.remove_env_path("MAYA_SCRIPT_PATH", paths["scripts"])
    for d in paths.get("plug_in_dirs", []):
        env_manager.remove_env_path("MAYA_PLUG_IN_PATH", d)
    if "icons" in paths:
        env_manager.remove_env_path("XBMLANGPATH", paths["icons"])
    if "presets" in paths:
        env_manager.remove_env_path("MAYA_PRESET_PATH", paths["presets"])


def _exec_user_setup(user_setup_path):
    """Execute a userSetup.py via maya.utils.executeDeferred.

    Outside Maya (e.g. in tests), the import fails and we silently no-op.
    Idempotency is the caller's responsibility.
    """
    try:
        import maya.utils as _mu
    except ImportError:
        return
    try:
        with open(user_setup_path, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError:
        return
    code = compile(source, user_setup_path, "exec")
    namespace = {"__file__": user_setup_path, "__name__": "__main__"}

    def _run():
        try:
            exec(code, namespace)
        except Exception:
            import traceback
            print("[Carton] userSetup.py failed: {}".format(user_setup_path))
            traceback.print_exc()

    _mu.executeDeferred(_run)


class MayaModuleHandler(PackageHandler):
    """Handle Autodesk Application Package / Maya module folders."""

    def install(self, package_dir, meta, env_manager):
        self._activate_once(package_dir, env_manager)

    def activate(self, package_dir, meta, env_manager):
        self._activate_once(package_dir, env_manager)

    def uninstall(self, package_dir, meta, env_manager):
        paths = resolve_paths(package_dir)
        _remove_paths(env_manager, paths)
        _ACTIVATED_DIRS.discard(os.path.normpath(package_dir))
        if os.path.exists(package_dir):
            shutil.rmtree(package_dir, ignore_errors=True)

    def launch(self, meta):
        entry = meta.get("entry_point", {}) or {}

        # Free-form Python launch command (set in EditDialog for modules
        # whose main window has no obvious top-level function).
        command = entry.get("command", "")
        if command:
            import __main__
            exec(command, __main__.__dict__)
            return

        # Structured python entry point: import + call
        if entry.get("type") == "python" and entry.get("module"):
            mod = importlib.import_module(entry["module"])
            func = getattr(mod, entry.get("function", "show"))
            return func()

        # Otherwise re-run userSetup.py to (re-)register menus/shelves
        package_dir = meta.get("local_path") or meta.get("path") or ""
        if package_dir and not os.path.isabs(package_dir):
            # installed.json stores a relative path; resolve under install dir
            install_dir = meta.get("_install_dir", "")
            if install_dir:
                package_dir = os.path.join(install_dir, package_dir)
        if not package_dir or not os.path.isdir(package_dir):
            raise RuntimeError(
                "Maya module directory not found for re-activation"
            )
        paths = resolve_paths(package_dir)
        if "user_setup" in paths:
            _exec_user_setup(paths["user_setup"])
        else:
            raise RuntimeError(
                "This module has no userSetup.py and no entry_point — "
                "nothing to launch."
            )

    def is_loaded(self, meta):
        package_dir = meta.get("local_path") or meta.get("path") or ""
        return os.path.normpath(package_dir) in _ACTIVATED_DIRS

    def _activate_once(self, package_dir, env_manager):
        paths = resolve_paths(package_dir)
        _apply_paths(env_manager, paths)
        key = os.path.normpath(package_dir)
        if "user_setup" in paths and key not in _ACTIVATED_DIRS:
            _exec_user_setup(paths["user_setup"])
            _ACTIVATED_DIRS.add(key)
