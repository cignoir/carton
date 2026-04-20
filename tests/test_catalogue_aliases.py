"""Tests for the v5.0 catalogue-name aliases (Step 4-A, phase 1).

The rename from RegistryEntry/registry_id/Config.registries to the
catalogue-* vocabulary is landing gradually so that no single commit
has to touch every consumer + UI + test at once. This first slice adds
the new names as aliases backed by the same storage as the old ones;
consumers migrate on their own schedule.

What we check:

* ``CatalogueEntry`` resolves to the exact same class as ``RegistryEntry``
  (identity alias, not a subclass) — so ``isinstance`` works either way
  and there's no chance of a parallel class hierarchy drifting.
* ``CatalogueEntry.catalogue_id`` mirrors ``registry_id`` bidirectionally:
  reads see the same value, writes go through identical normalisation.
* ``CatalogueEntry(catalogue_id=...)`` kwarg populates the same storage
  so a future writer that emits ``catalogue_id`` round-trips cleanly.
* ``from_dict`` accepts either JSON key (``registry_id`` or
  ``catalogue_id``) so a config.json rewritten by a v0.5 UI loads in an
  older reader that still has the shim.
* ``Config.catalogues`` is the same list as ``Config.registries`` —
  mutating one side is visible on the other, both read and write.
* ``add_catalogue`` / ``remove_catalogue`` / ``find_catalogue_by_id``
  delegate to the registry-named counterparts.

None of the tests touch on-disk config.json shape — that's a later
step once consumers have migrated.
"""

from carton.core.config import CatalogueEntry, Config, RegistryEntry


class TestEntryClassAlias:
    def test_catalogue_entry_is_registry_entry(self):
        """Identity — isinstance works both directions."""
        assert CatalogueEntry is RegistryEntry

    def test_isinstance_accepts_both_names(self):
        e = CatalogueEntry("studio", "/tmp/cat.json")
        assert isinstance(e, RegistryEntry)
        assert isinstance(e, CatalogueEntry)


class TestCatalogueIdProperty:
    def test_read_mirrors_registry_id(self):
        e = RegistryEntry("s", "/tmp/x.json", registry_id="ABC-123")
        # registry_id normalises to lowercase; catalogue_id reads the
        # same normalised storage.
        assert e.registry_id == "abc-123"
        assert e.catalogue_id == "abc-123"

    def test_write_normalises_and_syncs(self):
        e = RegistryEntry("s", "/tmp/x.json")
        e.catalogue_id = "  UUID-XYZ\n"
        # Same lowercase+strip as registry_id's __init__ path.
        assert e.registry_id == "uuid-xyz"
        assert e.catalogue_id == "uuid-xyz"

    def test_catalogue_id_kwarg_populates_same_storage(self):
        e = CatalogueEntry("s", "/tmp/x.json", catalogue_id="CAT-42")
        assert e.registry_id == "cat-42"

    def test_registry_id_wins_when_both_kwargs_given(self):
        """Live call sites all still pass registry_id; catalogue_id is
        a forward-compat seam. If both arrive, trust the old name so a
        half-migrated caller doesn't accidentally overwrite itself."""
        e = RegistryEntry(
            "s", "/tmp/x.json",
            registry_id="old", catalogue_id="new",
        )
        assert e.registry_id == "old"


class TestFromDictAcceptsEitherKey:
    def test_registry_id_key(self):
        e = RegistryEntry.from_dict({
            "name": "a", "path": "/x.json", "registry_id": "id-1",
        })
        assert e.catalogue_id == "id-1"

    def test_catalogue_id_key(self):
        """Forward-compat: a config.json written after the rename
        still round-trips through a reader that has only the alias."""
        e = RegistryEntry.from_dict({
            "name": "a", "path": "/x.json", "catalogue_id": "id-2",
        })
        assert e.registry_id == "id-2"

    def test_registry_id_preferred_when_both_present(self):
        e = RegistryEntry.from_dict({
            "name": "a", "path": "/x.json",
            "registry_id": "older", "catalogue_id": "newer",
        })
        # Matches __init__ precedence so there's one rule to remember.
        assert e.registry_id == "older"


class TestConfigCataloguesProperty:
    def test_catalogues_is_same_list_as_registries(self):
        cfg = Config()
        cfg.add_registry("a", "/p.json", registry_id="id-a")
        # Reading via the new name returns the same list object so
        # callers that iterate can't accidentally observe a stale copy.
        assert cfg.catalogues is cfg.registries

    def test_mutations_through_new_name_visible_on_old(self):
        cfg = Config()
        cfg.add_catalogue("b", "/q.json", catalogue_id="id-b")
        assert len(cfg.registries) == 1
        assert cfg.registries[0].name == "b"
        assert cfg.registries[0].registry_id == "id-b"

    def test_setter_replaces_the_list(self):
        cfg = Config(registries=[RegistryEntry("a", "/a.json")])
        cfg.catalogues = [RegistryEntry("c", "/c.json")]
        assert [r.name for r in cfg.registries] == ["c"]

    def test_find_catalogue_by_id_delegates(self):
        cfg = Config()
        cfg.add_registry("a", "/a.json", registry_id="uuid-1")
        cfg.add_registry("b", "/b.json", registry_id="uuid-2")
        found = cfg.find_catalogue_by_id("uuid-2")
        assert found is not None
        assert found.name == "b"
        # Missing id returns None, same as the registry-named method.
        assert cfg.find_catalogue_by_id("uuid-none") is None

    def test_remove_catalogue_removes_from_registries(self):
        cfg = Config()
        cfg.add_catalogue("a", "/a.json")
        cfg.add_catalogue("b", "/b.json")
        cfg.remove_catalogue("a")
        assert [r.name for r in cfg.registries] == ["b"]


class TestDualEmitOnDisk:
    """Step 4-A phase 3-b: write-side dual-emit.

    Our writer now emits both the legacy (``registries`` / ``registry_id``)
    and the v5.0 (``catalogues`` / ``catalogue_id``) shapes into the same
    config.json, with identical values pointing at the same underlying
    storage. This lets a v0.4.x reader still resolve the file while a
    v0.5.x reader (or CatalogueClient once it's wired up) picks up the
    new vocabulary. Step 4-C (post v0.5.0 rollout) drops the legacy keys.
    """

    def test_entry_to_dict_emits_both_ids(self):
        e = RegistryEntry("s", "/tmp/x.json", registry_id="uuid-a")
        d = e.to_dict()
        assert d["registry_id"] == "uuid-a"
        assert d["catalogue_id"] == "uuid-a"

    def test_entry_to_dict_omits_both_when_id_empty(self):
        """No ghost keys when the registry hasn't been fetched yet."""
        e = RegistryEntry("s", "/tmp/x.json")
        d = e.to_dict()
        assert "registry_id" not in d
        assert "catalogue_id" not in d

    def test_config_to_dict_emits_both_top_level_keys(self):
        cfg = Config()
        cfg.add_registry("a", "/p.json", registry_id="uuid-a")
        d = cfg.to_dict()
        assert "registries" in d
        assert "catalogues" in d
        assert len(d["registries"]) == 1
        assert len(d["catalogues"]) == 1
        # Same entry dict shape on both sides — the lists share the
        # underlying entry objects, so a mutation on one surfaces on the
        # other (important for any external tooling that hand-edits the
        # file after we've written it).
        assert d["registries"][0]["registry_id"] == "uuid-a"
        assert d["catalogues"][0]["catalogue_id"] == "uuid-a"


class TestLoadAcceptsEitherTopLevelKey:
    """Post dual-emit, the reader must tolerate a config.json that has
    only ``catalogues`` (future Step 4-C writers will drop ``registries``)
    or only ``registries`` (v0.4.x files still on disk). Same precedence
    as the dict-level rule: legacy wins when both are present."""

    def test_load_reads_catalogues_only(self):
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "catalogues": [
                        {"name": "modern", "path": "/m.json",
                         "catalogue_id": "uuid-m"}
                    ],
                }, f)
            cfg = Config.load(path)
            assert len(cfg.registries) == 1
            assert cfg.registries[0].name == "modern"
            assert cfg.registries[0].registry_id == "uuid-m"

    def test_load_reads_registries_only(self):
        """v0.4.x config.json stays readable verbatim."""
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "registries": [
                        {"name": "legacy", "path": "/l.json",
                         "registry_id": "uuid-l"}
                    ],
                }, f)
            cfg = Config.load(path)
            assert len(cfg.registries) == 1
            assert cfg.registries[0].name == "legacy"

    def test_load_when_both_keys_present_prefers_registries(self):
        """Dual-emit writer produces both — reader must not double-count."""
        import json
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "registries": [
                        {"name": "a", "path": "/a.json", "registry_id": "u1"}
                    ],
                    "catalogues": [
                        {"name": "a", "path": "/a.json", "catalogue_id": "u1"}
                    ],
                }, f)
            cfg = Config.load(path)
            assert len(cfg.registries) == 1

    def test_save_then_load_round_trip(self):
        """End-to-end: our own writer + our own reader converge cleanly."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "config.json")
            cfg = Config()
            cfg.add_registry("round", "/r.json", registry_id="uuid-r")
            cfg.save(path)
            restored = Config.load(path)
            assert len(restored.registries) == 1
            assert restored.registries[0].registry_id == "uuid-r"
            assert restored.registries[0].catalogue_id == "uuid-r"
