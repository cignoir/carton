"""Tests for v5.0 catalogue aliases on :class:`InstallerProfile`.

Parallels :mod:`tests.test_catalogue_aliases` (which covers the same
surface on ``Config`` / ``RegistryEntry``). Keeping the shim symmetrical
between Config and InstallerProfile means UI widgets that accept either
("bind this checkbox to target.catalogues") work without special casing.

What we check:

* ``profile.catalogues`` is the same list object as ``profile.registries``
  (list identity, not a copy).
* ``add_catalogue`` / ``remove_catalogue`` delegate to the registry-named
  methods.
* ``InstallerProfile.from_dict`` accepts either the ``registries`` or
  ``catalogues`` top-level key, and either ``registry_id`` or
  ``catalogue_id`` on each entry.
* Passing **both** ``registries`` and ``catalogues`` is rejected — we
  don't want a silent precedence rule users have to memorise.
* ``to_dict`` still emits the registries-named shape so existing profile
  readers keep working until the whole v5.0 migration lands.
"""

import pytest

from carton.core.profile import InstallerProfile, InvalidProfileError


_UUID_A = "11111111-2222-3333-4444-555555555555"
_UUID_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestCataloguesProperty:
    def test_catalogues_is_same_list_as_registries(self):
        prof = InstallerProfile()
        prof.add_registry("a", "/p.json", registry_id=_UUID_A)
        assert prof.catalogues is prof.registries

    def test_add_catalogue_round_trips_through_registries(self):
        prof = InstallerProfile()
        prof.add_catalogue("b", "/q.json", catalogue_id=_UUID_B)
        assert len(prof.registries) == 1
        assert prof.registries[0].name == "b"
        # catalogue_id and registry_id are the same storage.
        assert prof.registries[0].registry_id == _UUID_B
        assert prof.registries[0].catalogue_id == _UUID_B

    def test_remove_catalogue_removes_from_registries(self):
        prof = InstallerProfile()
        prof.add_catalogue("a", "/a.json")
        prof.add_catalogue("b", "/b.json")
        prof.remove_catalogue("a")
        assert [r.name for r in prof.registries] == ["b"]

    def test_catalogues_setter_replaces_list(self):
        prof = InstallerProfile()
        prof.add_registry("a", "/a.json")
        prof.catalogues = []
        assert prof.registries == []


class TestFromDictKeyCompat:
    def test_registries_key(self):
        prof = InstallerProfile.from_dict({
            "registries": [
                {"name": "r", "path": "/r.json", "registry_id": _UUID_A},
            ],
        })
        assert len(prof.registries) == 1
        assert prof.registries[0].registry_id == _UUID_A

    def test_catalogues_key(self):
        """Forward-compat: a profile written with the v5.0 top-level key
        must deserialise through this shim without needing a separate
        reader."""
        prof = InstallerProfile.from_dict({
            "catalogues": [
                {"name": "c", "path": "/c.json", "catalogue_id": _UUID_A},
            ],
        })
        assert len(prof.registries) == 1
        assert prof.registries[0].catalogue_id == _UUID_A

    def test_either_id_key_accepted_per_entry(self):
        """Independent of the top-level key choice: inner entries may
        carry either id key. Matches the RegistryEntry.from_dict rule."""
        prof = InstallerProfile.from_dict({
            "registries": [
                {"name": "a", "path": "/a.json", "catalogue_id": _UUID_A},
                {"name": "b", "path": "/b.json", "registry_id": _UUID_B},
            ],
        })
        assert prof.registries[0].registry_id == _UUID_A
        assert prof.registries[1].registry_id == _UUID_B

    def test_both_top_level_keys_rejected(self):
        """No silent precedence — fail loud if a hand-edit leaves both
        around mid-migration."""
        with pytest.raises(InvalidProfileError, match="pick one"):
            InstallerProfile.from_dict({
                "registries": [],
                "catalogues": [],
            })

    def test_registry_id_wins_when_both_id_keys_present(self):
        """Matches the RegistryEntry precedence rule so one consistent
        story across the codebase: old name wins until live callers
        have finished migrating."""
        prof = InstallerProfile.from_dict({
            "registries": [
                {
                    "name": "r", "path": "/r.json",
                    "registry_id": _UUID_A, "catalogue_id": _UUID_B,
                },
            ],
        })
        assert prof.registries[0].registry_id == _UUID_A

    def test_invalid_catalogue_id_is_rejected_with_useful_key_name(self):
        """The error message should point at whichever top-level key the
        user actually used — otherwise they go hunting for a 'registries'
        field in a file that only has 'catalogues'."""
        with pytest.raises(InvalidProfileError, match="catalogues"):
            InstallerProfile.from_dict({
                "catalogues": [
                    {"name": "c", "path": "/c.json", "catalogue_id": "not-a-uuid"},
                ],
            })


class TestToDictUnchanged:
    def test_to_dict_still_emits_registries_key(self):
        """On-disk format is still v4.0-shaped until we flip the writer
        — flipping early would strand v0.4.x readers."""
        prof = InstallerProfile()
        prof.add_catalogue("a", "/a.json", catalogue_id=_UUID_A)
        d = prof.to_dict()
        assert "registries" in d
        assert "catalogues" not in d
        assert d["registries"][0]["registry_id"] == _UUID_A
