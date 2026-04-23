"""Tests for the v0.5 catalogue-owned display_name flow.

The v0.5 refactor moved naming authority from subscribers (old config.json
``name`` key) to catalogue authors (``catalogue.json.display_name``). This
module covers the pieces that make the shift safe:

* ``CatalogueEntry`` accepts both the legacy subscriber-alias key and the
  new canonical form.
* ``CatalogueEntry.label`` keeps the UI rendering a non-empty string even
  when a just-added remote entry hasn't been fetched yet.
* :func:`_promote_display_names_to_catalogue` migrates pre-v0.5 aliases
  back into the catalogue.json on first load.
* :class:`CatalogueClient._cache_display_name` refreshes the entry's
  cached name from the fetched catalogue.
* Settings' URL → default-name helper handles the common GitHub raw shape
  and doesn't swallow the whole URL when the trailing segment is
  ``raw``/``main``/``master`` (the pre-v0.5 bug).
"""

import json
import os
import tempfile

from carton.core.config import (
    CatalogueEntry,
    Config,
    _promote_display_names_to_catalogue,
)


class TestDisplayNameBackCompat:
    def test_legacy_name_key_is_adopted(self):
        """Old config.json stored the subscriber alias under ``name``."""
        e = CatalogueEntry.from_dict({
            "name": "studio-alias",
            "path": "/srv/studio/catalogue.json",
        })
        assert e.display_name == "studio-alias"

    def test_display_name_key_wins_over_legacy_name(self):
        """When both keys are present (mid-migration), the new one wins."""
        e = CatalogueEntry.from_dict({
            "name": "old-alias",
            "display_name": "new-canonical",
            "path": "/p.json",
        })
        assert e.display_name == "new-canonical"

    def test_to_dict_emits_display_name_not_legacy_name(self):
        e = CatalogueEntry("/p.json", display_name="studio")
        d = e.to_dict()
        assert d.get("display_name") == "studio"
        assert "name" not in d


class TestLabelFallback:
    def test_label_prefers_display_name(self):
        e = CatalogueEntry("/srv/a/catalogue.json", display_name="Studio A")
        assert e.label == "Studio A"

    def test_label_falls_back_to_basename_for_local_path(self):
        e = CatalogueEntry("/srv/studio/catalogue.json")
        assert e.label == "catalogue.json"

    def test_label_falls_back_to_basename_for_url(self):
        """Freshly-added remote catalogues render something meaningful."""
        e = CatalogueEntry("https://example.com/team/catalogue.json")
        assert e.label == "catalogue.json"

    def test_label_survives_empty_path(self):
        """Personal catalogue virtual entry has an empty path."""
        e = CatalogueEntry("", display_name="Personal")
        assert e.label == "Personal"


class TestPromoteDisplayNamesToCatalogue:
    """Migrate pre-v0.5 subscriber aliases back into the local catalogue.json."""

    def test_writes_back_when_catalogue_missing_display_name(self, tmp_path):
        cat_path = tmp_path / "catalogue.json"
        cat_path.write_text(
            json.dumps({
                "schema_version": "5.0",
                "catalogue_id": "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
                "packages": {},
            }),
            encoding="utf-8",
        )
        entry = CatalogueEntry(
            str(cat_path), display_name="legacy-studio-alias",
        )
        _promote_display_names_to_catalogue([entry])
        data = json.loads(cat_path.read_text(encoding="utf-8"))
        assert data["display_name"] == "legacy-studio-alias"

    def test_does_not_overwrite_existing_display_name(self, tmp_path):
        """Author's choice takes precedence over any subscriber alias."""
        cat_path = tmp_path / "catalogue.json"
        cat_path.write_text(
            json.dumps({
                "schema_version": "5.0",
                "catalogue_id": "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
                "display_name": "authors-pick",
                "packages": {},
            }),
            encoding="utf-8",
        )
        entry = CatalogueEntry(
            str(cat_path), display_name="subscriber-alias",
        )
        _promote_display_names_to_catalogue([entry])
        data = json.loads(cat_path.read_text(encoding="utf-8"))
        assert data["display_name"] == "authors-pick"

    def test_skips_remote_entries(self, tmp_path):
        """Remote catalogues can't be mutated from the subscriber side."""
        entry = CatalogueEntry(
            "https://example.com/catalogue.json", display_name="alias",
        )
        # Should not raise (remote is silently skipped).
        _promote_display_names_to_catalogue([entry])

    def test_legacy_config_triggers_migration_on_load(self, tmp_path, monkeypatch):
        """Full end-to-end: legacy config.json → catalogue.json gets stamped."""
        cat_path = tmp_path / "catalogue.json"
        cat_path.write_text(
            json.dumps({
                "schema_version": "5.0",
                "catalogue_id": "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
                "packages": {},
            }),
            encoding="utf-8",
        )
        # Craft a pre-v0.5 config.json carrying the old ``name`` key.
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({
                "catalogues": [
                    {"name": "studio-legacy", "path": str(cat_path)},
                ],
            }),
            encoding="utf-8",
        )
        # Pretend this IS the canonical location so the migration fires.
        monkeypatch.setattr(
            "carton.core.config.default_config_path",
            lambda: str(config_path),
        )
        # Avoid seeding the user's real profile directory during the load.
        monkeypatch.setattr(
            "carton.core.config.Config._ensure_default_profile_and_overlay",
            lambda self: None,
        )
        Config.load()
        # catalogue.json now carries the author-owned display_name.
        data = json.loads(cat_path.read_text(encoding="utf-8"))
        assert data["display_name"] == "studio-legacy"


class TestCatalogueClientDisplayNameCache:
    """CatalogueClient should refresh the entry's display_name on every read."""

    def test_cache_display_name_picks_up_fetched_value(self, tmp_path):
        from carton.core.catalogue_client import CatalogueClient
        from carton.core.source_cache import SourceCache

        cat_path = tmp_path / "catalogue.json"
        cat_path.write_text(json.dumps({
            "schema_version": "5.0",
            "catalogue_id": "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
            "display_name": "authors-pick",
            "packages": {},
        }), encoding="utf-8")

        config = Config(install_dir=str(tmp_path / "install"))
        config.add_catalogue(str(cat_path), display_name="stale-cache")
        client = CatalogueClient(
            config, cache=SourceCache(cache_dir=str(tmp_path / "cache")),
        )
        client.fetch()

        assert config.catalogues[0].display_name == "authors-pick"

    def test_cache_display_name_keeps_stale_when_source_empty(self, tmp_path):
        """An empty value in catalogue.json must not clobber a usable cache."""
        from carton.core.catalogue_client import CatalogueClient
        from carton.core.source_cache import SourceCache

        cat_path = tmp_path / "catalogue.json"
        cat_path.write_text(json.dumps({
            "schema_version": "5.0",
            "catalogue_id": "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
            "packages": {},
        }), encoding="utf-8")

        config = Config(install_dir=str(tmp_path / "install"))
        config.add_catalogue(str(cat_path), display_name="useful-cache")
        client = CatalogueClient(
            config, cache=SourceCache(cache_dir=str(tmp_path / "cache")),
        )
        client.fetch()

        assert config.catalogues[0].display_name == "useful-cache"


class TestDefaultNameFromUrl:
    """Regression tests for the pre-v0.5 `parts[-3]` URL-name bug."""

    def _fn(self):
        # Lazy import — settings_widgets pulls Qt at module level.
        from carton.ui.settings_widgets import _default_name_from_url
        return _default_name_from_url

    def test_github_raw_url_picks_repo_segment(self):
        """/owner/repo/branch/catalogue.json → repo"""
        fn = self._fn()
        url = "https://raw.githubusercontent.com/acme/studio-tools/main/catalogue.json"
        assert fn(url) == "studio-tools"

    def test_github_raw_url_without_trailing_filename(self):
        fn = self._fn()
        url = "https://raw.githubusercontent.com/acme/studio-tools/main"
        assert fn(url) == "studio-tools"

    def test_non_github_url_drops_plumbing_segments(self):
        """Pre-v0.5 bug: a trailing ``main`` segment produced the full URL."""
        fn = self._fn()
        url = "https://studio.example.com/catalogues/shared/main/catalogue.json"
        # Should collapse past the plumbing ``main`` and stop at ``shared``.
        assert fn(url) == "shared"

    def test_short_url_falls_back_to_host(self):
        fn = self._fn()
        assert fn("https://example.com/catalogue.json") == "example.com"

    def test_malformed_url_returns_something(self):
        """No crashes on a garbage input — caller may still need a label."""
        fn = self._fn()
        # urlparse treats non-URL input as a bare path, so we just assert
        # the function returns a non-empty string rather than raising.
        assert fn("not a url at all")
