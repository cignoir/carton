"""Carton bootstrap — lightweight entry point executed at Maya startup.

Called from userSetup.py, performs the following:
1. Apply pending_update.json if present (self-update)
2. Add install_dir to sys.path
3. Call carton.startup()
"""

import json
import os
import shutil
import sys
import traceback
import zipfile

def _find_default_install_dir():
    """Detect the Maya application directory."""
    # 1. MAYA_APP_DIR environment variable (for custom setups)
    env_dir = os.environ.get("MAYA_APP_DIR")
    if env_dir:
        candidate = os.path.join(env_dir, "carton")
        if os.path.exists(os.path.join(candidate, "config.json")):
            return candidate

    # 2. Documents/maya/carton (Windows default)
    docs_maya = os.path.expanduser("~/Documents/maya/carton")
    if os.path.exists(os.path.join(docs_maya, "config.json")):
        return docs_maya

    # 3. ~/maya/carton (Linux/Mac default)
    home_maya = os.path.expanduser("~/maya/carton")
    if os.path.exists(os.path.join(home_maya, "config.json")):
        return home_maya

    # Fallback: default based on OS
    if sys.platform == "win32":
        return docs_maya
    return home_maya


def _get_install_dir():
    """Read install_dir from config.json. Use default if not found."""
    default = _find_default_install_dir()
    config_path = os.path.join(default, "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("install_dir", default)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _apply_pending_update(install_dir):
    """Apply Carton self-update if pending_update.json exists."""
    pending_file = os.path.join(install_dir, "pending_update.json")
    if not os.path.exists(pending_file):
        return

    with open(pending_file, "r", encoding="utf-8") as f:
        pending = json.load(f)

    carton_dir = os.path.join(install_dir, "carton")
    backup_dir = os.path.join(install_dir, "carton.bak")
    staged_zip = os.path.join(install_dir, pending["staged_zip"])

    if not os.path.exists(staged_zip):
        print("[Carton] Staged zip not found: {}".format(staged_zip))
        os.remove(pending_file)
        return

    try:
        # Backup
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        if os.path.exists(carton_dir):
            os.rename(carton_dir, backup_dir)

        # Extract
        with zipfile.ZipFile(staged_zip, "r") as zf:
            zf.extractall(install_dir)

        # Success -> cleanup
        os.remove(pending_file)
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        if os.path.exists(staged_zip):
            os.remove(staged_zip)

        # Remove staging directory if empty
        staging_dir = os.path.dirname(staged_zip)
        if os.path.isdir(staging_dir) and not os.listdir(staging_dir):
            os.rmdir(staging_dir)

        print("[Carton] Updated to v{}".format(pending["version"]))

    except Exception:
        traceback.print_exc()
        # Rollback
        if os.path.exists(backup_dir):
            if os.path.exists(carton_dir):
                shutil.rmtree(carton_dir)
            os.rename(backup_dir, carton_dir)
        if os.path.exists(pending_file):
            os.remove(pending_file)
        print("[Carton] Update failed, rolled back to previous version")


def start():
    """Bootstrap Carton."""
    install_dir = _get_install_dir()

    # Apply self-update
    _apply_pending_update(install_dir)

    # Add to sys.path
    if install_dir not in sys.path:
        sys.path.insert(0, install_dir)

    # Start Carton
    import carton
    carton.startup()
