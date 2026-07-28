"""Carton bootstrap — lightweight entry point executed at Maya startup.

Called from userSetup.py, performs the following:
1. Apply pending_update.json if present (self-update)
2. Add the bootstrap dir (where the carton/ package lives) to sys.path
3. Call carton.startup() — Config inside the package figures out install_dir

The bootstrap dir is fixed to the default OS location. install_dir (a
separate config value) controls only where DATA is stored (packages/,
installed.json, caches), not where the Python package lives.
"""

import hashlib
import json
import os
import shutil
import sys
import traceback
import zipfile


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _find_bootstrap_dir():
    """Location of the carton/ Python package. Never moves."""
    if sys.platform == "win32":
        return os.path.normpath(os.path.expanduser("~/Documents/maya/carton"))
    return os.path.normpath(os.path.expanduser("~/maya/carton"))


def _discard_pending(pending_file, reason):
    """Delete a pending-update record we refuse to act on.

    Removing the file is the whole point: this runs before
    ``carton.startup()``, so anything that escapes as an exception stops
    Carton from loading — and a record left on disk would reproduce that
    failure at every single Maya start until the user found and deleted
    the file by hand.
    """
    print("[Carton] Discarding pending update ({})".format(reason))
    try:
        os.remove(pending_file)
    except OSError as e:
        print("[Carton] Could not remove {}: {}".format(pending_file, e))


def _read_pending(pending_file):
    """Return the pending-update record, or None if it is unusable.

    A truncated or key-missing record is discarded here rather than
    allowed to raise. It reaches this state through an interrupted write
    or a damaged disk, and the correct response to "I can't tell what
    update was staged" is to forget it and boot the version already
    installed — never to refuse to boot.
    """
    try:
        with open(pending_file, "r", encoding="utf-8") as f:
            pending = json.load(f)
    except (OSError, ValueError) as e:
        _discard_pending(pending_file, "unreadable: {}".format(e))
        return None
    if not isinstance(pending, dict) or not pending.get("staged_zip"):
        _discard_pending(pending_file, "no staged_zip recorded")
        return None
    return pending


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

    pending = _read_pending(pending_file)
    if pending is None:
        return

    carton_dir = os.path.join(bootstrap_dir, "carton")
    backup_dir = os.path.join(bootstrap_dir, "carton.bak")
    staged_zip = os.path.join(bootstrap_dir, pending["staged_zip"])

    if not os.path.exists(staged_zip):
        print("[Carton] Staged zip not found: {}".format(staged_zip))
        os.remove(pending_file)
        return

    # Re-verify right before extracting: the zip may have sat on disk for
    # days since SelfUpdater staged (and hash-checked) it. A mismatch means
    # corruption or tampering — discard the update and keep the current
    # version rather than extracting unknown bytes over carton/.
    expected_sha256 = (pending.get("sha256") or "").lower()
    if expected_sha256:
        try:
            actual = _sha256_of(staged_zip)
        except OSError:
            actual = ""
        if actual != expected_sha256:
            print("[Carton] Staged update sha256 mismatch — discarding "
                  "(expected {}, got {})".format(expected_sha256, actual))
            os.remove(pending_file)
            os.remove(staged_zip)
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

        print("[Carton] Updated to v{}".format(pending.get("version", "?")))

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

    # Apply self-update (extracts carton/ into bootstrap_dir).
    #
    # Never fatal: the update path touches the filesystem in ways that can
    # fail for reasons that have nothing to do with the copy of Carton
    # already installed (locked files, antivirus, a full disk). Launching
    # the version on disk is always better than not launching at all, so
    # anything unexpected here is reported and stepped over.
    try:
        _apply_pending_update(bootstrap_dir)
    except Exception:
        traceback.print_exc()
        print("[Carton] Self-update skipped; starting the installed version")

    # Make the carton/ package importable
    if bootstrap_dir not in sys.path:
        sys.path.insert(0, bootstrap_dir)

    # Start Carton — carton.startup() will load Config and honor whatever
    # install_dir the user has configured for DATA storage.
    import carton
    carton.startup()
