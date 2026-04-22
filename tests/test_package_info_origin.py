"""Tests for PackageInfo's v5.0 origin support (Step 1).

Covers:

* ``origin`` kwarg on :class:`PackageInfo.__init__` — accepted, stored,
  defaults to ``None`` so v4.0 call sites stay untouched.
* :meth:`PackageInfo.from_origin` — builds from a v5.0 catalogue row +
  :class:`Origin` instance, reusing :meth:`from_registry_entry` for
  scalar fields.
* :meth:`PackageInfo.to_installed_dict` emits an ``origin`` block when
  one is attached, and omits it otherwise.
* Round-trip through installed.json (to_installed_dict →
  from_installed_entry) preserves the origin's type + locator.
* Embedded origin serialisation strips the (large) ``versions`` payload —
  we don't want catalogue state leaking into installed.json.
"""

from carton.core.origins import EmbeddedOrigin, GithubOrigin
from carton.models.package_info import PackageInfo


_EMBEDDED_VERSIONS = {
    "1.0.0": {
        "maya_versions": ["2024", "2025"],
        "download_url": "packages/studio/tool/1.0.0/tool-1.0.0.zip",
        "sha256": "a" * 64,
        "size_bytes": 123,
        "released_at": "2026-03-01T00:00:00Z",
    }
}


def _catalogue_pkg_data():
    """Legacy-shape dict that CatalogueClient hands to from_origin."""
    return {
        "namespace": "studio",
        "name": "tool",
        "display_name": "Studio Tool",
        "description": "hi",
        "author": "me",
        "type": "python_package",
        "tags": ["rig"],
        "latest_version": "1.0.0",
        "versions": dict(_EMBEDDED_VERSIONS),
    }


class TestOriginField:
    def test_origin_defaults_to_none(self):
        info = PackageInfo(pkg_id="studio/tool", namespace="studio", name="tool")
        assert info.origin is None

    def test_origin_stored_when_given(self):
        origin = GithubOrigin(repo="studio/tool")
        info = PackageInfo(
            pkg_id="studio/tool", namespace="studio", name="tool", origin=origin
        )
        assert info.origin is origin


class TestFromOrigin:
    def test_copies_scalar_fields_from_pkg_data(self):
        origin = EmbeddedOrigin(
            versions=_EMBEDDED_VERSIONS, latest_version="1.0.0", base_dir="/tmp/cat"
        )
        info = PackageInfo.from_origin(
            "studio/tool", _catalogue_pkg_data(), version_key="1.0.0", origin=origin,
        )
        assert info.id == "studio/tool"
        assert info.namespace == "studio"
        assert info.name == "tool"
        assert info.display_name == "Studio Tool"
        assert info.description == "hi"
        assert info.version == "1.0.0"
        assert info.maya_versions == ["2024", "2025"]
        assert info.tags == ["rig"]
        assert info.origin is origin

    def test_defaults_version_to_latest(self):
        origin = EmbeddedOrigin(versions=_EMBEDDED_VERSIONS, base_dir="")
        info = PackageInfo.from_origin(
            "studio/tool", _catalogue_pkg_data(), origin=origin
        )
        assert info.version == "1.0.0"

    def test_accepts_none_origin(self):
        """from_origin without an origin still works (e.g. placeholder rows)."""
        info = PackageInfo.from_origin(
            "studio/tool", _catalogue_pkg_data(), version_key="1.0.0",
        )
        assert info.origin is None
        assert info.id == "studio/tool"


class TestInstalledDictSerialisation:
    def test_origin_absent_when_none(self):
        info = PackageInfo(
            pkg_id="studio/tool", namespace="studio", name="tool",
            version="1.0.0", source="registry",
        )
        d = info.to_installed_dict()
        assert "origin" not in d

    def test_github_origin_round_trips(self):
        origin = GithubOrigin(repo="studio/tool", ref="main")
        info = PackageInfo(
            pkg_id="studio/tool", namespace="studio", name="tool",
            version="1.0.0", source="registry", origin=origin,
        )
        d = info.to_installed_dict()
        assert d["origin"] == {"type": "github", "repo": "studio/tool", "ref": "main"}

        restored = PackageInfo.from_installed_entry("studio/tool", d)
        assert isinstance(restored.origin, GithubOrigin)
        assert restored.origin.to_dict() == origin.to_dict()

    def test_embedded_origin_strips_versions_on_persist(self):
        """Embedded origin's versions payload is catalogue state, not install state.

        Keeping it would bloat installed.json with duplicated catalogue rows
        — we only need the origin's identity so reinstall can re-resolve.
        """
        origin = EmbeddedOrigin(
            versions=_EMBEDDED_VERSIONS, latest_version="1.0.0", base_dir="/tmp/cat",
        )
        info = PackageInfo(
            pkg_id="studio/tool", namespace="studio", name="tool",
            version="1.0.0", source="registry", origin=origin,
        )
        d = info.to_installed_dict()
        assert d["origin"] == {"type": "embedded"}
        # Round-trip: the rebuilt origin has no versions but still
        # identifies as embedded, so catalogue-side re-resolution can fill
        # them back in.
        restored = PackageInfo.from_installed_entry("studio/tool", d)
        assert isinstance(restored.origin, EmbeddedOrigin)
        assert restored.origin.list_versions() == {}

    def test_corrupted_origin_in_installed_entry_is_dropped(self):
        """Malformed origin dict must not block loading installed.json."""
        info = PackageInfo.from_installed_entry(
            "studio/tool",
            {
                "namespace": "studio",
                "name": "tool",
                "version": "1.0.0",
                "type": "python_package",
                "installed_at": "2026-04-20T00:00:00Z",
                "source": "registry",
                "origin": {"type": "nonexistent-kind"},
            },
        )
        assert info.origin is None
        assert info.id == "studio/tool"

    def test_non_dict_origin_value_tolerated(self):
        """Defensive: garbage ``origin`` key shouldn't crash loading."""
        info = PackageInfo.from_installed_entry(
            "studio/tool",
            {
                "namespace": "studio",
                "name": "tool",
                "version": "1.0.0",
                "type": "python_package",
                "installed_at": "2026-04-20T00:00:00Z",
                "source": "registry",
                "origin": "not-a-dict",
            },
        )
        assert info.origin is None
