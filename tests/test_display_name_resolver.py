"""Tests for resolve_display_name()."""

from carton.core.display_name_resolver import resolve_display_name


class TestResolveDisplayName:
    def test_my_tools_entry_uses_installed(self):
        installed = {"source": "local", "display_name": "My Pretty Name"}
        registry = {"display_name": "Registry Says So"}
        assert resolve_display_name("ns/x", installed, registry) == "My Pretty Name"

    def test_registry_entry_uses_registry(self):
        installed = {"source": "registry"}
        registry = {"display_name": "Registry Says So"}
        assert resolve_display_name("ns/x", installed, registry) == "Registry Says So"

    def test_double_bound_uses_registry(self):
        # source=registry + local_path → registry SoT for display
        installed = {
            "source": "registry",
            "local_path": "/tmp/source",
            "display_name": "Stale Local Name",
        }
        registry = {"display_name": "Canonical Name"}
        assert resolve_display_name("ns/x", installed, registry) == "Canonical Name"

    def test_falls_back_to_installed_when_no_registry(self):
        installed = {"display_name": "Whatever"}
        assert resolve_display_name("ns/x", installed, None) == "Whatever"

    def test_falls_back_to_pkg_id_when_nothing(self):
        assert resolve_display_name("ns/x", None, None) == "ns/x"
        assert resolve_display_name("ns/x", {}, {}) == "ns/x"

    def test_uses_entry_name_as_last_resort(self):
        installed = {"name": "bare_name"}
        assert resolve_display_name("ns/x", installed, None) == "bare_name"
