"""Tests for Step 4-A Phase 3: CatalogueClient wired into carton.startup().

The switch from :class:`RegistryClient` to :class:`CatalogueClient` at
startup is the point where v5.0 actually starts driving the UI — every
``registry_client.get_packages()`` call in ``main_window`` now goes
through the catalogue-aware client.

What this file verifies:

* :func:`carton.startup` produces a :class:`CatalogueClient` in the
  ``_registry_client`` slot (name kept for UI compatibility; instance
  type is what changed).
* :meth:`CatalogueClient._fetch_icons_archive` was ported from
  RegistryClient and preserves the same "network errors are not fatal"
  behaviour — a missing / broken icons.zip must never take down the
  whole catalogue fetch.
* Successful icons.zip fetch extracts into ``config.icon_cache_dir``,
  so the UI's thumbnail lookups keep finding files.

UI-level behaviour (actually rendering thumbnails, live Maya integration)
is deliberately out of scope for pytest; a manual smoke test in Maya
covers that side of the migration.
"""

import io
import json
import os
import zipfile

import pytest

import carton
from carton.core.catalogue_client import CatalogueClient
from carton.core.config import Config, CatalogueEntry


# ---- startup wiring -------------------------------------------------------

class TestStartupUsesCatalogueClient:
    def _reset_globals(self):
        """Undo any prior startup() so we can re-run it in isolation."""
        carton._initialized = False
        carton._config = None
        carton._env_mgr = None
        carton._install_mgr = None
        carton._registry_client = None
        carton._downloader = None
        carton._self_updater = None
        carton._script_mgr = None
        carton._publisher = None

    def test_registry_client_slot_holds_catalogue_client_after_startup(self):
        """The global name stays ``_registry_client`` (UI compat) but
        the object is now a CatalogueClient."""
        self._reset_globals()
        try:
            carton.startup()
            assert isinstance(carton._registry_client, CatalogueClient)
        finally:
            self._reset_globals()


# ---- icons.zip fetch parity ----------------------------------------------

class _FakeResponse(object):
    """Minimal urlopen-response stand-in."""
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


def _build_icons_zip(file_map):
    """Return in-memory ZIP bytes with the given ``{name: bytes}`` entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in file_map.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestFetchIconsArchive:
    def test_missing_archive_swallowed(self, tmp_path, monkeypatch):
        """A 404 / network error on icons.zip must not raise."""
        config = Config(install_dir=str(tmp_path / "install"))
        entry = CatalogueEntry("remote", "https://example.com/reg/catalogue.json")

        def _raise(*args, **kwargs):
            raise RuntimeError("offline")
        monkeypatch.setattr(
            "carton.core.catalogue_client.urlopen", _raise,
        )

        client = CatalogueClient(config)
        # Should return cleanly — not propagate the RuntimeError.
        client._fetch_icons_archive(entry)

    def test_successful_fetch_extracts_into_cache_dir(self, tmp_path, monkeypatch):
        config = Config(install_dir=str(tmp_path / "install"))
        entry = CatalogueEntry("remote", "https://example.com/reg/catalogue.json")
        zip_bytes = _build_icons_zip({
            "studio-icon.png": b"fakepng",
            "other.png": b"fake2",
        })

        def _fake_urlopen(req, timeout=None):
            return _FakeResponse(zip_bytes)
        monkeypatch.setattr(
            "carton.core.catalogue_client.urlopen", _fake_urlopen,
        )

        client = CatalogueClient(config)
        client._fetch_icons_archive(entry)

        cache_dir = config.icon_cache_dir
        assert os.path.exists(os.path.join(cache_dir, "studio-icon.png"))
        assert os.path.exists(os.path.join(cache_dir, "other.png"))

    def test_corrupt_zip_swallowed(self, tmp_path, monkeypatch):
        """Garbage bytes shouldn't crash the fetch either."""
        config = Config(install_dir=str(tmp_path / "install"))
        entry = CatalogueEntry("remote", "https://example.com/reg/catalogue.json")

        def _fake_urlopen(req, timeout=None):
            return _FakeResponse(b"not a zip at all")
        monkeypatch.setattr(
            "carton.core.catalogue_client.urlopen", _fake_urlopen,
        )

        client = CatalogueClient(config)
        # Must not raise — BadZipFile is caught by the broad ``except``.
        client._fetch_icons_archive(entry)
