"""Abstract base class for package handlers."""

from abc import ABC, abstractmethod


class PackageHandler(ABC):
    """Type-specific install and launch logic."""

    @abstractmethod
    def install(self, package_dir, meta, env_manager):
        """Install the package and register it in the Maya environment."""
        ...

    @abstractmethod
    def uninstall(self, package_dir, meta, env_manager):
        """Uninstall the package and remove it from the Maya environment."""
        ...

    @abstractmethod
    def activate(self, package_dir, meta, env_manager):
        """Activate the package at Maya startup."""
        ...

    @abstractmethod
    def launch(self, meta):
        """Launch action triggered from the UI."""
        ...

    @abstractmethod
    def is_loaded(self, meta):
        """Check whether the package is currently loaded in Maya."""
        ...
