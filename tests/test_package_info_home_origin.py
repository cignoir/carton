"""Tests for PackageInfo's v5.0 ``home_origin`` field.

Covers:

* ``home_origin`` kwarg on :class:`PackageInfo.__init__` — accepted,
  stored, defaults to ``{}`` when not supplied.
* :meth:`PackageInfo.to_installed_dict` emits ``home_origin`` when
  non-empty, omits it when empty.
* Round-trip through installed.json
  (``to_installed_dict`` → ``from_installed_entry``) preserves the
  field verbatim for embedded, github, url, and local variants.
* Legacy installed.json entries that carry only a ``home_registry``
  field load cleanly — the field is simply ignored.
* :meth:`CatalogueEntry.to_home_origin_meta` produces the v5.0 embedded
  payload shape (``type``/``catalogue_name``/``catalogue_id``/``hint``).
"""

from carton.core.config import CatalogueEntry
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

    def test_no_home_origin_omits_key(self):
        d = self._info().to_installed_dict()
        assert "home_origin" not in d

    def test_home_origin_emitted_when_set(self):
        modern = {"type": "github", "repo": "studio/tool"}
        d = self._info(home_origin=modern).to_installed_dict()
        assert d["home_origin"] == modern

    def test_embedded_round_trip(self):
        modern = {"type": "embedded", "catalogue_name": "studio-main",
                  "catalogue_id": _UUID}
        d = self._info(home_origin=modern).to_installed_dict()
        restored = PackageInfo.from_installed_entry("studio/tool", d)
        assert restored.home_origin == modern

    def test_github_origin_round_trip(self):
        modern = {"type": "github", "repo": "studio/tool", "ref": "v1.0.0"}
        d = self._info(home_origin=modern).to_installed_dict()
        restored = PackageInfo.from_installed_entry("studio/tool", d)
        assert restored.home_origin == modern

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

    def test_legacy_home_registry_field_is_ignored(self):
        """v0.4 installed.json entries carrying only ``home_registry``
        load cleanly — the field is silently dropped, ``home_origin``
        stays empty. Re-saving the entry scrubs the legacy key."""
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
        assert restored.home_origin == {}
        assert "home_registry" not in restored.to_installed_dict()


class TestCatalogueEntryHomeOriginMeta:
    def test_local_entry_emits_embedded_variant(self):
        entry = CatalogueEntry(display_name="studio-main",
            path="/studio/registry/catalogue.json",
            catalogue_id=_UUID,
        )
        meta = entry.to_home_origin_meta()
        assert meta["type"] == "embedded"
        assert meta["catalogue_name"] == "studio-main"
        assert meta["catalogue_id"] == _UUID
        assert meta["hint"] == entry.path

    def test_remote_url_included_as_hint(self):
        entry = CatalogueEntry(display_name="public",
            path="https://example.com/registry/catalogue.json",
            catalogue_id=_UUID,
        )
        meta = entry.to_home_origin_meta()
        assert meta["hint"] == "https://example.com/registry/catalogue.json"

    def test_missing_catalogue_id_omits_it(self):
        entry = CatalogueEntry(display_name="studio-main", path=".")
        meta = entry.to_home_origin_meta()
        assert "catalogue_id" not in meta
        assert meta["catalogue_name"] == "studio-main"
        assert meta["type"] == "embedded"

    def test_empty_path_omits_hint(self):
        """``.`` (the normalised form of an empty path) means no hint."""
        entry = CatalogueEntry(display_name="studio-main", path="", catalogue_id=_UUID)
        meta = entry.to_home_origin_meta()
        assert "hint" not in meta
