"""Tests for resolve_entry_point()."""

import json
import os
import tempfile

from carton.core.entry_point_resolver import resolve_entry_point


def _write_inner(package_dir, entry_point):
    os.makedirs(package_dir, exist_ok=True)
    with open(os.path.join(package_dir, "package.json"), "w", encoding="utf-8") as f:
        json.dump({"entry_point": entry_point}, f)


class TestResolveEntryPoint:
    def test_inner_package_json_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            inner = {"type": "python", "module": "foo", "function": "show"}
            _write_inner(tmp, inner)

            installed = {"entry_point": {"type": "python", "module": "stale"}}
            registry = {"entry_point": {"type": "python", "module": "stalest"}}
            result = resolve_entry_point(installed, package_dir=tmp,
                                         registry_data=registry)
            assert result == inner

    def test_falls_back_to_installed_for_my_tools(self):
        # No package_dir: My Tools entries store entry_point on the
        # installed.json side (no zip to read from).
        installed = {"entry_point": {"type": "python", "module": "mine", "function": "go"}}
        result = resolve_entry_point(installed, package_dir=None)
        assert result == installed["entry_point"]

    def test_falls_back_to_registry_preview(self):
        # Browsed but not installed: only the registry hint is available.
        registry = {"entry_point": {"type": "python", "module": "preview", "function": "show"}}
        result = resolve_entry_point({}, package_dir=None, registry_data=registry)
        assert result == registry["entry_point"]

    def test_returns_empty_when_nothing_resolves(self):
        assert resolve_entry_point({}) == {}
        assert resolve_entry_point({}, package_dir="/no/such/dir") == {}

    def test_inner_with_no_entry_point_field_is_authoritative(self):
        """If inner package.json explicitly has no entry_point, that wins
        over installed/registry — the package author has spoken."""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "package.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "foo"}, f)
            # No entry_point in inner — resolver should return {} not the
            # registry preview.
            registry = {"entry_point": {"type": "python", "module": "fallback"}}
            result = resolve_entry_point({}, package_dir=tmp, registry_data=registry)
            assert result == {}

    def test_unreadable_inner_falls_through(self):
        """A missing package.json is not the same as an empty entry_point —
        falls through to the next source instead of returning {}."""
        with tempfile.TemporaryDirectory() as tmp:
            # Don't create package.json at all
            registry = {"entry_point": {"type": "python", "module": "fallback"}}
            result = resolve_entry_point({}, package_dir=tmp, registry_data=registry)
            assert result == registry["entry_point"]
