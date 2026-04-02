"""Carton local configuration management."""

import json
import os
import sys


def _detect_install_dir():
    """Return the default install_dir based on the OS."""
    if sys.platform == "win32":
        return os.path.expanduser("~/Documents/maya/carton")
    return os.path.expanduser("~/maya/carton")


_DEFAULT_INSTALL_DIR = _detect_install_dir()


class RegistryEntry:
    """Registry configuration entry."""

    def __init__(self, name, path):
        self.name = name
        self.path = path

    def to_dict(self):
        return {"name": self.name, "path": self.path}

    @classmethod
    def from_dict(cls, d):
        return cls(name=d.get("name", ""), path=d.get("path", ""))

    @property
    def base_dir(self):
        """Parent directory of registry.json. Used for relative path resolution."""
        return os.path.dirname(os.path.normpath(self.path))


class Config:
    """Read/write config.json."""

    def __init__(
        self,
        registries=None,
        install_dir=_DEFAULT_INSTALL_DIR,
        auto_check_updates=True,
        github_repo="cignoir/carton",
    ):
        self.registries = registries or []
        self.install_dir = install_dir
        self.auto_check_updates = auto_check_updates
        self.github_repo = github_repo

    @classmethod
    def load(cls, path=None):
        """Load config.json. Return defaults if not found."""
        if path is None:
            path = os.path.join(_DEFAULT_INSTALL_DIR, "config.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            registries = [RegistryEntry.from_dict(r) for r in data.get("registries", [])]
            return cls(
                registries=registries,
                install_dir=data.get("install_dir", _DEFAULT_INSTALL_DIR),
                auto_check_updates=data.get("auto_check_updates", True),
                github_repo=data.get("github_repo", "cignoir/carton"),
            )
        return cls()

    def save(self, path=None):
        """Write to config.json."""
        if path is None:
            path = os.path.join(self.install_dir, "config.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def to_dict(self):
        return {
            "registries": [r.to_dict() for r in self.registries],
            "install_dir": self.install_dir,
            "auto_check_updates": self.auto_check_updates,
            "github_repo": self.github_repo,
        }

    def add_registry(self, name, path):
        """Add a registry."""
        self.registries.append(RegistryEntry(name, path))

    def remove_registry(self, name):
        """Remove a registry by name."""
        self.registries = [r for r in self.registries if r.name != name]

    @property
    def packages_dir(self):
        return os.path.join(self.install_dir, "packages")

    @property
    def installed_json_path(self):
        return os.path.join(self.install_dir, "installed.json")

    @property
    def staging_dir(self):
        return os.path.join(self.install_dir, ".staging")
