"""Tests for resolve_entry_point()."""

import json
import os
import tempfile

from carton.core.entry_point_resolver import resolve_entry_point, normalize_entry_point


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


class TestNormalizeEntryPoint:
    def test_well_formed_passes_through(self):
        ep = {"type": "python", "module": "foo", "function": "show"}
        assert normalize_entry_point(ep) == ep

    def test_legacy_string_form_becomes_python(self):
        ep = normalize_entry_point("my_tool.ui:show")
        assert ep == {"type": "python", "module": "my_tool.ui", "function": "show"}

    def test_malformed_string_passes_through(self):
        # No colon → not a module:function — can't safely rewrite.
        assert normalize_entry_point("just_a_name") == "just_a_name"

    def test_bare_module_dict_infers_python(self):
        ep = normalize_entry_point({"module": "ref_switcher"})
        assert ep["type"] == "python"
        assert ep["module"] == "ref_switcher"
        assert ep["function"] == "show"

    def test_bare_module_dict_preserves_function(self):
        ep = normalize_entry_point({"module": "foo", "function": "run"})
        assert ep == {"type": "python", "module": "foo", "function": "run"}

    def test_bare_script_procedure_infers_mel(self):
        ep = normalize_entry_point({"script": "foo.mel", "procedure": "foo"})
        assert ep["type"] == "mel"
        assert ep["script"] == "foo.mel"
        assert ep["procedure"] == "foo"

    def test_bare_mll_file_infers_plugin(self):
        ep = normalize_entry_point({"file": "helper.mll"})
        assert ep["type"] == "plugin"

    def test_unclassifiable_dict_passes_through(self):
        # Nothing we can infer from — caller (launcher) should surface the
        # error rather than guess.
        ep = {"random": "junk"}
        assert normalize_entry_point(ep) == ep

    def test_empty_dict_passes_through(self):
        assert normalize_entry_point({}) == {}


class TestResolveEntryPointNormalisation:
    """resolve_entry_point applies normalize_entry_point to every source."""

    def test_legacy_string_in_installed_json_gets_normalised(self):
        installed = {"entry_point": "ref_switcher.ui:show"}
        result = resolve_entry_point(installed)
        assert result == {
            "type": "python", "module": "ref_switcher.ui", "function": "show",
        }

    def test_bare_module_in_registry_preview_gets_normalised(self):
        registry = {"entry_point": {"module": "preview_tool"}}
        result = resolve_entry_point({}, registry_data=registry)
        assert result["type"] == "python"
        assert result["module"] == "preview_tool"
