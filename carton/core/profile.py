"""Installer profile — seed configuration baked into a custom installer.

A profile is the subset of :class:`~carton.core.config.Config` that makes
sense to ship inside a customized Carton installer for a team or project:

* the catalogue list (the main reason for building a custom installer)
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
from carton.core.uuid_id import is_valid_uuid


class InvalidProfileError(ValueError):
    """Raised when a profile JSON file fails validation."""


# Fields the profile is allowed to set. Anything outside this set is
# rejected during validation so typos in hand-edited JSON surface early.
_ALLOWED_KEYS = {
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
        catalogues=None,
        language="auto",
        auto_check_updates=True,
        github_repo="cignoir/carton",
        proxy="",
    ):
        # Use CatalogueEntry so the shared settings widgets can treat
        # Config and InstallerProfile interchangeably.
        self.catalogues = []
        for r in catalogues or []:
            if isinstance(r, CatalogueEntry):
                self.catalogues.append(r)
            else:
                # Legacy profile JSON stored the subscriber alias under
                # ``name``; accept it as a display_name fallback so
                # hand-edited studio profiles keep loading.
                display_name = r.get("display_name") or r.get("name", "")
                self.catalogues.append(CatalogueEntry(
                    path=r.get("path", ""),
                    catalogue_id=r.get("catalogue_id", ""),
                    display_name=display_name,
                ))
        self.language = language
        self.auto_check_updates = bool(auto_check_updates)
        self.github_repo = github_repo
        self.proxy = proxy

    def add_catalogue(self, path, catalogue_id="", display_name=""):
        self.catalogues.append(
            CatalogueEntry(path, catalogue_id=catalogue_id, display_name=display_name),
        )

    def remove_catalogue(self, path_or_id):
        key = (path_or_id or "").strip()
        if not key:
            return
        key_id = key.lower()
        self.catalogues = [
            r for r in self.catalogues
            if r.path != key and (not r.catalogue_id or r.catalogue_id != key_id)
        ]

    @classmethod
    def blank(cls):
        """An empty profile (no catalogues, defaults for everything else)."""
        return cls()

    @classmethod
    def from_config(cls, config):
        """Snapshot the relevant fields of a live ``Config``.

        Used by the Profile Builder when the user picks "Copy current"
        as a starting point.
        """
        return cls(
            catalogues=[
                CatalogueEntry(
                    path=r.path,
                    catalogue_id=getattr(r, "catalogue_id", ""),
                    display_name=getattr(r, "display_name", ""),
                )
                for r in getattr(config, "catalogues", []) or []
            ],
            language=getattr(config, "language", "auto"),
            auto_check_updates=getattr(config, "auto_check_updates", True),
            github_repo=getattr(config, "github_repo", "cignoir/carton"),
            proxy=getattr(config, "proxy", ""),
        )

    def to_dict(self):
        return {
            "catalogues": [r.to_dict() for r in self.catalogues],
            "language": self.language,
            "auto_check_updates": self.auto_check_updates,
            "github_repo": self.github_repo,
            "proxy": self.proxy,
        }

    @classmethod
    def from_dict(cls, data):
        """Build from a dict (e.g. parsed JSON). Validates structure.

        v0.4.x profiles used ``registries`` / ``registry_id`` keys; we
        accept those as aliases for ``catalogues`` / ``catalogue_id`` so
        hand-edited or git-tracked profile files keep loading across the
        cutover. The next ``save()`` rewrites the file with v5.0 keys.
        Same-file co-existence of both keys is rejected — we pick a
        winner rather than silently preferring one.
        """
        if not isinstance(data, dict):
            raise InvalidProfileError(
                "Profile must be a JSON object, got {}".format(type(data).__name__)
            )

        if "registries" in data and "catalogues" in data:
            raise InvalidProfileError(
                "profile has both 'catalogues' and 'registries' — drop the "
                "legacy 'registries' key"
            )
        if "registries" in data:
            data = dict(data)
            data["catalogues"] = data.pop("registries")

        unknown = set(data.keys()) - _ALLOWED_KEYS
        if unknown:
            raise InvalidProfileError(
                "Unknown profile field(s): {}".format(", ".join(sorted(unknown)))
            )

        entries = data.get("catalogues", [])
        if not isinstance(entries, list):
            raise InvalidProfileError("'catalogues' must be a list")
        normalized = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise InvalidProfileError(
                    "catalogues[{}] must be an object".format(i)
                )
            # display_name is owned by catalogue.json (authors pick it);
            # profile entries may carry a stale snapshot but it's not
            # required. ``name`` is accepted as a legacy alias so hand-
            # edited studio profiles from v0.4.x keep loading.
            display_name = entry.get("display_name") or entry.get("name", "")
            path = entry.get("path", "")
            if display_name and not isinstance(display_name, str):
                raise InvalidProfileError(
                    "catalogues[{}].display_name must be a string".format(i)
                )
            if not path or not isinstance(path, str):
                raise InvalidProfileError(
                    "catalogues[{}].path is required".format(i)
                )
            if "registry_id" in entry and "catalogue_id" in entry:
                raise InvalidProfileError(
                    "catalogues[{}] has both 'catalogue_id' and "
                    "'registry_id' — drop the legacy key".format(i)
                )
            cid_raw = entry.get("catalogue_id") or entry.get("registry_id") or ""
            catalogue_id = cid_raw or ""
            if catalogue_id:
                if not isinstance(catalogue_id, str):
                    raise InvalidProfileError(
                        "catalogues[{}].catalogue_id must be a string".format(i)
                    )
                if not is_valid_uuid(catalogue_id):
                    raise InvalidProfileError(
                        "catalogues[{}].catalogue_id must be a UUID".format(i)
                    )
                catalogue_id = catalogue_id.strip().lower()
            normalized.append({
                "display_name": display_name, "path": path,
                "catalogue_id": catalogue_id,
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
            catalogues=normalized,
            language=language,
            auto_check_updates=auto_check_updates,
            github_repo=github_repo,
            proxy=proxy,
        )

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
