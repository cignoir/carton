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


_VALID_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def profiles_dir():
    """Return the directory profiles live in. Created on demand."""
    return os.path.join(default_bootstrap_dir(), "profiles")


def _path_for(name):
    return os.path.join(profiles_dir(), "{}.json".format(name))


def is_valid_name(name):
    """Profile names must be filesystem-safe single-segment identifiers."""
    return bool(name) and bool(_VALID_NAME.match(name))


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
