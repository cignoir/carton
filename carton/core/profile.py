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

from carton.core.config import CatalogueEntry
from carton.core.registry_id import is_valid_registry_id


class InvalidProfileError(ValueError):
    """Raised when a profile JSON file fails validation."""


# Fields the profile is allowed to set. Anything outside this set is
# rejected during validation so typos in hand-edited JSON surface early.
# ``catalogues`` is the v5.0 alias for ``registries`` — exactly one of
# the two may appear in a given profile (the validator rejects both
# being set simultaneously to avoid silent precedence rules).
_ALLOWED_KEYS = {
    "registries",
    "catalogues",
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
        # Use CatalogueEntry so the shared settings widgets can treat
        # Config and InstallerProfile interchangeably.
        self.registries = []
        for r in registries or []:
            if isinstance(r, CatalogueEntry):
                self.registries.append(r)
            else:
                self.registries.append(CatalogueEntry(
                    name=r.get("name", ""),
                    path=r.get("path", ""),
                    catalogue_id=r.get("catalogue_id", ""),
                ))
        self.language = language
        self.auto_check_updates = bool(auto_check_updates)
        self.github_repo = github_repo
        self.proxy = proxy

    # ---- mutation helpers (mirror Config so widgets can call either) ----

    def add_registry(self, name, path, catalogue_id=""):
        self.registries.append(CatalogueEntry(name, path, catalogue_id))

    def remove_registry(self, name):
        self.registries = [r for r in self.registries if r.name != name]

    # ---- v5.0 catalogue-name aliases -----------------------------------
    # Same storage as the registry-named surface above. Lets UI widgets
    # and config readers that have adopted v5.0 terminology work against
    # InstallerProfile without a special case.

    @property
    def catalogues(self):
        """v5.0 alias for :attr:`registries` — same list object."""
        return self.registries

    @catalogues.setter
    def catalogues(self, value):
        self.registries = list(value) if value is not None else []

    def add_catalogue(self, name, path, catalogue_id=""):
        """v5.0 alias for :meth:`add_registry`."""
        self.add_registry(name, path, catalogue_id)

    def remove_catalogue(self, name):
        """v5.0 alias for :meth:`remove_registry`."""
        self.remove_registry(name)

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
                CatalogueEntry(
                    name=r.name, path=r.path,
                    catalogue_id=getattr(r, "catalogue_id", ""),
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

        # Accept either JSON key for the registry / catalogue list, but
        # refuse both at once so there's no silent precedence rule: if a
        # hand-editor is halfway through a rename and both slip in, fail
        # loud rather than picking one arbitrarily.
        has_registries = "registries" in data
        has_catalogues = "catalogues" in data
        if has_registries and has_catalogues:
            raise InvalidProfileError(
                "profile has both 'registries' and 'catalogues' — pick one"
            )
        list_key = "catalogues" if has_catalogues else "registries"
        entries = data.get(list_key, [])
        if not isinstance(entries, list):
            raise InvalidProfileError("{!r} must be a list".format(list_key))
        normalized = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise InvalidProfileError(
                    "{}[{}] must be an object".format(list_key, i)
                )
            name = entry.get("name", "")
            path = entry.get("path", "")
            if not name or not isinstance(name, str):
                raise InvalidProfileError(
                    "{}[{}].name is required".format(list_key, i)
                )
            if not path or not isinstance(path, str):
                raise InvalidProfileError(
                    "{}[{}].path is required".format(list_key, i)
                )
            cid_raw = entry.get("catalogue_id", "")
            catalogue_id = cid_raw or ""
            if catalogue_id:
                if not isinstance(catalogue_id, str):
                    raise InvalidProfileError(
                        "{}[{}].catalogue_id must be a string".format(list_key, i)
                    )
                if not is_valid_registry_id(catalogue_id):
                    raise InvalidProfileError(
                        "{}[{}].catalogue_id must be a UUID".format(list_key, i)
                    )
                catalogue_id = catalogue_id.strip().lower()
            normalized.append({
                "name": name, "path": path, "catalogue_id": catalogue_id,
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
