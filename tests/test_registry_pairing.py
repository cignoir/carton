"""Unit tests for the registry pairing helper's pure logic.

The Qt-dependent bits (stamp_local_registry_with_prompt,
resolve_duplicate_registry) can't be exercised headlessly here, but the
duplicate-entry resolver is framework-free and carries the logic that
decides whether a pairing flow should surface the "already registered"
dialog — which is where the most user-facing bug lives.
"""

import os

from carton.core.config import Config, RegistryEntry
from carton.ui._registry_pairing import find_duplicate_entry


_UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
_UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"


class TestFindDuplicateEntry:
    def test_no_rid_returns_none(self):
        c = Config()
        c.add_registry("a", "/p/a.json", registry_id=_UUID_A)
        assert find_duplicate_entry(c.registries, "", "/p/new.json") is None

    def test_no_match_returns_none(self):
        c = Config()
        c.add_registry("a", "/p/a.json", registry_id=_UUID_A)
        assert find_duplicate_entry(c.registries, _UUID_B, "/p/new.json") is None

    def test_match_returns_entry(self):
        c = Config()
        c.add_registry("a", "/p/a.json", registry_id=_UUID_A)
        match = find_duplicate_entry(c.registries, _UUID_A, "/p/new.json")
        assert match is not None
        assert match.name == "a"

    def test_same_path_not_a_duplicate(self):
        """Re-selecting a registry already in the list is not a duplicate."""
        c = Config()
        c.add_registry("a", "/p/a.json", registry_id=_UUID_A)
        same = os.path.normpath("/p/a.json")
        assert find_duplicate_entry(c.registries, _UUID_A, same) is None

    def test_ignore_excludes_paired_remote(self):
        """The paired remote is expected to share the UUID with its mirror.

        This is the exact bug the user hit: picking a local mirror during
        a remote→mirror pairing flow tripped the duplicate dialog because
        ``find_registry_by_id`` returned the remote that triggered the
        pairing in the first place. ``ignore`` lets the caller pass the
        paired remote so we can skip it.
        """
        c = Config()
        c.add_registry(
            "guru2", "https://example.com/guru2/registry.json",
            registry_id=_UUID_A,
        )
        remote_entry = c.registries[0]
        match = find_duplicate_entry(
            c.registries, _UUID_A,
            "F:/workspace/carton-guru2/registry.json",
            ignore=[remote_entry],
        )
        assert match is None, (
            "paired_remote must not be flagged as its own mirror's duplicate"
        )

    def test_ignore_does_not_skip_other_entries(self):
        """If a SECOND entry shares the UUID, it's still a real duplicate."""
        c = Config()
        c.add_registry(
            "guru2-remote", "https://example.com/guru2/registry.json",
            registry_id=_UUID_A,
        )
        c.add_registry(
            "guru2-local", "F:/workspace/carton-guru2/registry.json",
            registry_id=_UUID_A,
        )
        remote_entry = c.registries[0]
        local_entry = c.registries[1]
        match = find_duplicate_entry(
            c.registries, _UUID_A,
            "F:/workspace/other/registry.json",
            ignore=[remote_entry],
        )
        assert match is local_entry
