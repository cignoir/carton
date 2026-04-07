"""Filesystem store for switchable runtime profiles.

Profiles live as ``<bootstrap_dir>/profiles/<name>.json`` and reuse the
:class:`~carton.core.profile.InstallerProfile` JSON shape, so a profile
authored in the Profile Builder can be dropped straight into the runtime
profiles directory and used to seed alternate Carton configurations
(work / hobby / per-project, etc.).

Only the *overlay* fields (registries, language, proxy, github_repo,
auto_check_updates) are managed here. Machine-local state — install_dir,
installed packages — stays in ``config.json`` and is shared across all
profiles. That keeps switching profiles purely a "view + fetch source"
change with no need to relocate files or restart Maya.
"""

import os
import re

from carton.core.config import default_bootstrap_dir
from carton.core.profile import InstallerProfile, InvalidProfileError


# Filesystem-unsafe characters (Windows is the strictest of the three
# major platforms, so this list also covers macOS and Linux). Anything
# else — including non-ASCII letters like Japanese — is allowed because
# profile names are user-facing labels, not identifiers on the wire.
_FORBIDDEN_CHARS = set('\\/:*?"<>|')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Canonical name of the always-present fallback profile. The runtime
# treats it identically to any other profile — it just always exists,
# can't be deleted, and can't be reused as a name for new profiles.
DEFAULT_PROFILE_NAME = "default"


def profiles_dir():
    """Return the directory profiles live in. Created on demand."""
    return os.path.join(default_bootstrap_dir(), "profiles")


def _path_for(name):
    return os.path.join(profiles_dir(), "{}.json".format(name))


def is_valid_name(name):
    """Profile names must be safe to use as a filename on any OS."""
    if not name or not isinstance(name, str):
        return False
    # Reject leading/trailing spaces and dots — Windows silently strips
    # them, so two distinct names can collide on disk.
    if name != name.strip(" ."):
        return False
    if any(ch in _FORBIDDEN_CHARS for ch in name):
        return False
    if any(ord(ch) < 32 for ch in name):
        return False
    if name.upper() in _WINDOWS_RESERVED:
        return False
    return True


def list_profiles():
    """Return a sorted list of profile names available on disk."""
    d = profiles_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for entry in os.listdir(d):
        if entry.endswith(".json"):
            out.append(entry[:-5])
    return sorted(out)


def load_profile(name):
    """Load a profile by name. Raises :class:`InvalidProfileError`."""
    if not is_valid_name(name):
        raise InvalidProfileError("Invalid profile name: {!r}".format(name))
    path = _path_for(name)
    if not os.path.exists(path):
        raise InvalidProfileError("Profile not found: {}".format(name))
    return InstallerProfile.load(path)


def save_profile(name, profile):
    """Persist a profile under the given name. Creates the dir if needed."""
    if not is_valid_name(name):
        raise InvalidProfileError("Invalid profile name: {!r}".format(name))
    os.makedirs(profiles_dir(), exist_ok=True)
    profile.save(_path_for(name))


def delete_profile(name):
    """Delete a profile file. No-op if it doesn't exist."""
    if not is_valid_name(name):
        raise InvalidProfileError("Invalid profile name: {!r}".format(name))
    path = _path_for(name)
    if os.path.exists(path):
        os.remove(path)


def profile_exists(name):
    return is_valid_name(name) and os.path.exists(_path_for(name))


def ordered_profiles(preferred_order):
    """Return profile names ordered by ``preferred_order`` first.

    Names from ``preferred_order`` that exist on disk come first in the
    given order. Any remaining profile files are appended alphabetically
    so brand-new profiles appear without manual ordering work.
    """
    on_disk = set(list_profiles())
    out = []
    seen = set()
    for name in preferred_order or []:
        if name in on_disk and name not in seen:
            out.append(name)
            seen.add(name)
    for name in sorted(on_disk - seen):
        out.append(name)
    return out
