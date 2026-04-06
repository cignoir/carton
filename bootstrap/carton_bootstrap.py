"""Carton bootstrap — lightweight entry point executed at Maya startup.

Called from userSetup.py, performs the following:
1. Apply pending_update.json if present (self-update)
2. Add the bootstrap dir (where the carton/ package lives) to sys.path
3. Call carton.startup() — Config inside the package figures out install_dir

The bootstrap dir is fixed to the default OS location. install_dir (a
separate config value) controls only where DATA is stored (packages/,
installed.json, caches), not where the Python package lives.
"""

import json
import os
import shutil
import sys
import traceback
import zipfile

def _find_bootstrap_dir():
    """Location of the carton/ Python package. Never moves."""
    if sys.platform == "win32":
        return os.path.normpath(os.path.expanduser("~/Documents/maya/carton"))
    return os.path.normpath(os.path.expanduser("~/maya/carton"))


def _apply_pending_update(bootstrap_dir):
    """Apply Carton self-update if pending_update.json exists.

    Both pending_update.json and the staged zip live next to the carton/
    Python package in ``bootstrap_dir`` (not under install_dir), so that
    self-update still works regardless of where the user pointed
    install_dir.
    """
    pending_file = os.path.join(bootstrap_dir, "pending_update.json")
    if not os.path.exists(pending_file):
        return

    with open(pending_file, "r", encoding="utf-8") as f:
        pending = json.load(f)

    carton_dir = os.path.join(bootstrap_dir, "carton")
    backup_dir = os.path.join(bootstrap_dir, "carton.bak")
    staged_zip = os.path.join(bootstrap_dir, pending["staged_zip"])

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
            zf.extractall(bootstrap_dir)

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
    bootstrap_dir = _find_bootstrap_dir()

    # Apply self-update (extracts carton/ into bootstrap_dir)
    _apply_pending_update(bootstrap_dir)

    # Make the carton/ package importable
    if bootstrap_dir not in sys.path:
        sys.path.insert(0, bootstrap_dir)

    # Start Carton — carton.startup() will load Config and honor whatever
    # install_dir the user has configured for DATA storage.
    import carton
    carton.startup()
