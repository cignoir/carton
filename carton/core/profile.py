"""Installer profile — seed configuration baked into a custom installer.

A profile is the subset of :class:`~carton.core.config.Config` that makes
sense to ship inside a customized Carton installer for a team or project:

* the registry list (the main reason for building a custom installer)
* language preference
* HTTP proxy
* auto-update behavior
* the GitHub repo to self-update from (for studios maintaining a fork)

Notably absent: ``install_dir`` (machine-specific), and any UI state.

Profiles are persisted as plain JSON so admins can edit them in any text
editor and Git-track them alongside their other studio configuration.
The CLI installer builder consumes them via ``--profile <path>`` and
embeds the values into the generated ``install_carton.py``; the embedded
values are then written to ``config.json`` on first install only — never
overwriting an existing config.
"""

import json
import os

from carton.core.config import RegistryEntry
from carton.core.registry_id import is_valid_registry_id


class InvalidProfileError(ValueError):
    """Raised when a profile JSON file fails validation."""


# Fields the profile is allowed to set. Anything outside this set is
# rejected during validation so typos in hand-edited JSON surface early.
_ALLOWED_KEYS = {
    "registries",
    "language",
    "auto_check_updates",
    "github_repo",
    "proxy",
}

_VALID_LANGUAGES = ("auto", "ja", "en")


class InstallerProfile:
    """Carton settings to bake into a customized installer.

    All fields are optional. An empty profile (``InstallerProfile()``)
    produces an installer that behaves identically to the upstream one.
    """

    def __init__(
        self,
        registries=None,
        language="auto",
        auto_check_updates=True,
        github_repo="cignoir/carton",
        proxy="",
    ):
        # Use RegistryEntry so the shared settings widgets can treat
        # Config and InstallerProfile interchangeably.
        self.registries = []
        for r in registries or []:
            if isinstance(r, RegistryEntry):
                self.registries.append(r)
            else:
                self.registries.append(RegistryEntry(
                    name=r.get("name", ""),
                    path=r.get("path", ""),
                    registry_id=r.get("registry_id", ""),
                ))
        self.language = language
        self.auto_check_updates = bool(auto_check_updates)
        self.github_repo = github_repo
        self.proxy = proxy

    # ---- mutation helpers (mirror Config so widgets can call either) ----

    def add_registry(self, name, path, registry_id=""):
        self.registries.append(RegistryEntry(name, path, registry_id))

    def remove_registry(self, name):
        self.registries = [r for r in self.registries if r.name != name]

    # ---- factories -------------------------------------------------------

    @classmethod
    def blank(cls):
        """An empty profile (no registries, defaults for everything else)."""
        return cls()

    @classmethod
    def from_config(cls, config):
        """Snapshot the relevant fields of a live ``Config``.

        Used by the Profile Builder when the user picks "Copy current"
        as a starting point.
        """
        return cls(
            registries=[
                RegistryEntry(
                    name=r.name, path=r.path,
                    registry_id=getattr(r, "registry_id", ""),
                )
                for r in getattr(config, "registries", []) or []
            ],
            language=getattr(config, "language", "auto"),
            auto_check_updates=getattr(config, "auto_check_updates", True),
            github_repo=getattr(config, "github_repo", "cignoir/carton"),
            proxy=getattr(config, "proxy", ""),
        )

    # ---- serialization ---------------------------------------------------

    def to_dict(self):
        return {
            "registries": [r.to_dict() for r in self.registries],
            "language": self.language,
            "auto_check_updates": self.auto_check_updates,
            "github_repo": self.github_repo,
            "proxy": self.proxy,
        }

    @classmethod
    def from_dict(cls, data):
        """Build from a dict (e.g. parsed JSON). Validates structure."""
        if not isinstance(data, dict):
            raise InvalidProfileError(
                "Profile must be a JSON object, got {}".format(type(data).__name__)
            )

        unknown = set(data.keys()) - _ALLOWED_KEYS
        if unknown:
            raise InvalidProfileError(
                "Unknown profile field(s): {}".format(", ".join(sorted(unknown)))
            )

        registries = data.get("registries", [])
        if not isinstance(registries, list):
            raise InvalidProfileError("'registries' must be a list")
        normalized = []
        for i, entry in enumerate(registries):
            if not isinstance(entry, dict):
                raise InvalidProfileError(
                    "registries[{}] must be an object".format(i)
                )
            name = entry.get("name", "")
            path = entry.get("path", "")
            if not name or not isinstance(name, str):
                raise InvalidProfileError(
                    "registries[{}].name is required".format(i)
                )
            if not path or not isinstance(path, str):
                raise InvalidProfileError(
                    "registries[{}].path is required".format(i)
                )
            registry_id = entry.get("registry_id", "")
            if registry_id:
                if not isinstance(registry_id, str):
                    raise InvalidProfileError(
                        "registries[{}].registry_id must be a string".format(i)
                    )
                if not is_valid_registry_id(registry_id):
                    raise InvalidProfileError(
                        "registries[{}].registry_id must be a UUID".format(i)
                    )
                registry_id = registry_id.strip().lower()
            normalized.append({
                "name": name, "path": path, "registry_id": registry_id,
            })

        language = data.get("language", "auto")
        if language not in _VALID_LANGUAGES:
            raise InvalidProfileError(
                "language must be one of {}, got {!r}".format(
                    _VALID_LANGUAGES, language
                )
            )

        auto_check_updates = data.get("auto_check_updates", True)
        if not isinstance(auto_check_updates, bool):
            raise InvalidProfileError("auto_check_updates must be a boolean")

        github_repo = data.get("github_repo", "cignoir/carton")
        if not isinstance(github_repo, str):
            raise InvalidProfileError("github_repo must be a string")

        proxy = data.get("proxy", "")
        if not isinstance(proxy, str):
            raise InvalidProfileError("proxy must be a string")

        return cls(
            registries=normalized,
            language=language,
            auto_check_updates=auto_check_updates,
            github_repo=github_repo,
            proxy=proxy,
        )

    # ---- file I/O --------------------------------------------------------

    def save(self, path):
        """Write the profile to a JSON file with stable formatting."""
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")

    @classmethod
    def load(cls, path):
        """Load and validate a profile from a JSON file.

        Raises :class:`InvalidProfileError` if the file is malformed JSON,
        is not an object, contains unknown fields, or fails any of the
        per-field validation rules.
        """
        if not os.path.exists(path):
            raise InvalidProfileError("Profile file not found: {}".format(path))
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise InvalidProfileError(
                "Invalid JSON in {}: {}".format(path, e)
            )
        return cls.from_dict(data)
