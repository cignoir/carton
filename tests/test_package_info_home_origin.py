"""Tests for PackageInfo's v5.0 ``home_origin`` alias layer.

Covers:

* ``home_origin`` kwarg on :class:`PackageInfo.__init__` — accepted,
  stored, defaults to ``{}`` so v0.4 call sites stay untouched.
* ``home_registry`` and ``home_origin`` co-exist without auto-sync —
  consumers in the alias period touch one or the other.
* :meth:`PackageInfo.to_installed_dict` emits ``home_origin`` (when
  non-empty) alongside ``home_registry``, omitting either when empty.
* Round-trip through installed.json
  (``to_installed_dict`` → ``from_installed_entry``) preserves both
  fields verbatim for embedded, github, url, and local variants.
* :meth:`CatalogueEntry.to_home_origin_meta` produces the v5.0 embedded
  payload shape (``type``/``catalogue_name``/``catalogue_id``/``hint``).
"""

from carton.core.config import CatalogueEntry, CatalogueEntry
from carton.models.package_info import PackageInfo


_UUID = "deadbeef-dead-beef-dead-beefdeadbeef"


class TestHomeOriginField:
    def test_home_origin_defaults_to_empty(self):
        info = PackageInfo(pkg_id="studio/tool", namespace="studio", name="tool")
        assert info.home_origin == {}

    def test_home_origin_stored_when_given(self):
        payload = {"type": "github", "repo": "studio/tool"}
        info = PackageInfo(
            pkg_id="studio/tool",
            namespace="studio",
            name="tool",
            home_origin=payload,
        )
        assert info.home_origin == payload

    def test_home_origin_independent_of_home_registry(self):
        """Two fields, no auto-sync — alias period semantics."""
        legacy = {"name": "studio-main", "registry_id": _UUID}
        modern = {"type": "embedded", "catalogue_name": "studio-main",
                  "catalogue_id": _UUID}
        info = PackageInfo(
            pkg_id="studio/tool",
            namespace="studio",
            name="tool",
            home_registry=legacy,
            home_origin=modern,
        )
        assert info.home_registry == legacy
        assert info.home_origin == modern

    def test_home_registry_without_home_origin_still_works(self):
        legacy = {"name": "studio-main", "registry_id": _UUID}
        info = PackageInfo(
            pkg_id="studio/tool",
            namespace="studio",
            name="tool",
            home_registry=legacy,
        )
        assert info.home_registry == legacy
        assert info.home_origin == {}


class TestInstalledDictRoundtrip:
    def _info(self, **kwargs):
        base = dict(
            pkg_id="studio/tool",
            namespace="studio",
            name="tool",
            version="1.0.0",
            pkg_type="python_package",
            installed_at="2026-04-20T00:00:00Z",
            source="registry",
            path="packages/studio/tool",
        )
        base.update(kwargs)
        return PackageInfo(**base)

    def test_neither_field_omitted_from_dict(self):
        d = self._info().to_installed_dict()
        assert "home_registry" not in d
        assert "home_origin" not in d

    def test_home_registry_only_emits_legacy_key(self):
        legacy = {"name": "studio-main", "registry_id": _UUID}
        d = self._info(home_registry=legacy).to_installed_dict()
        assert d["home_registry"] == legacy
        assert "home_origin" not in d

    def test_home_origin_only_emits_modern_key(self):
        modern = {"type": "github", "repo": "studio/tool"}
        d = self._info(home_origin=modern).to_installed_dict()
        assert d["home_origin"] == modern
        assert "home_registry" not in d

    def test_both_fields_round_trip(self):
        legacy = {"name": "studio-main", "registry_id": _UUID}
        modern = {"type": "embedded", "catalogue_name": "studio-main",
                  "catalogue_id": _UUID}
        d = self._info(home_registry=legacy, home_origin=modern).to_installed_dict()
        assert d["home_registry"] == legacy
        assert d["home_origin"] == modern

        restored = PackageInfo.from_installed_entry("studio/tool", d)
        assert restored.home_registry == legacy
        assert restored.home_origin == modern

    def test_github_origin_round_trip(self):
        modern = {"type": "github", "repo": "studio/tool", "ref": "v1.0.0"}
        d = self._info(home_origin=modern).to_installed_dict()
        restored = PackageInfo.from_installed_entry("studio/tool", d)
        assert restored.home_origin == modern
        assert restored.home_registry == {}

    def test_url_origin_round_trip(self):
        modern = {"type": "url", "url": "https://example.com/tool-package.json"}
        d = self._info(home_origin=modern).to_installed_dict()
        restored = PackageInfo.from_installed_entry("studio/tool", d)
        assert restored.home_origin == modern

    def test_local_origin_round_trip(self):
        modern = {"type": "local", "path": "/Users/me/dev/tool"}
        d = self._info(home_origin=modern).to_installed_dict()
        restored = PackageInfo.from_installed_entry("studio/tool", d)
        assert restored.home_origin == modern

    def test_legacy_installed_json_without_home_origin_loads(self):
        """v0.4 installed.json entries don't carry home_origin — loading
        must still work and leave the field empty."""
        legacy_entry = {
            "namespace": "studio",
            "name": "tool",
            "version": "1.0.0",
            "type": "python_package",
            "installed_at": "2026-04-20T00:00:00Z",
            "source": "registry",
            "path": "packages/studio/tool",
            "home_registry": {"name": "studio-main", "registry_id": _UUID},
        }
        restored = PackageInfo.from_installed_entry("studio/tool", legacy_entry)
        assert restored.home_registry == {"name": "studio-main", "registry_id": _UUID}
        assert restored.home_origin == {}


class TestCatalogueEntryHomeOriginMeta:
    def test_local_entry_emits_embedded_variant(self):
        entry = CatalogueEntry(
            name="studio-main",
            path="/studio/registry/catalogue.json",
            catalogue_id=_UUID,
        )
        meta = entry.to_home_origin_meta()
        assert meta["type"] == "embedded"
        assert meta["catalogue_name"] == "studio-main"
        assert meta["catalogue_id"] == _UUID
        assert meta["hint"] == entry.path

    def test_remote_url_included_as_hint(self):
        entry = CatalogueEntry(
            name="public",
            path="https://example.com/registry/catalogue.json",
            catalogue_id=_UUID,
        )
        meta = entry.to_home_origin_meta()
        assert meta["hint"] == "https://example.com/registry/catalogue.json"

    def test_missing_registry_id_omits_catalogue_id(self):
        entry = CatalogueEntry(name="studio-main", path=".")
        meta = entry.to_home_origin_meta()
        assert "catalogue_id" not in meta
        assert meta["catalogue_name"] == "studio-main"
        assert meta["type"] == "embedded"

    def test_empty_path_omits_hint(self):
        """Same normalisation rule as to_home_meta — ``.`` means no hint."""
        entry = CatalogueEntry(name="studio-main", path="", catalogue_id=_UUID)
        meta = entry.to_home_origin_meta()
        assert "hint" not in meta

    def test_registry_entry_alias_emits_same_payload(self):
        """CatalogueEntry and CatalogueEntry are the same class — helper
        works through either name."""
        entry = CatalogueEntry(
            name="studio-main",
            path="/studio/registry/catalogue.json",
            catalogue_id=_UUID,
        )
        meta = entry.to_home_origin_meta()
        assert meta["type"] == "embedded"
        assert meta["catalogue_name"] == "studio-main"
