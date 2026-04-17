"""Tests for the installed.json entry classification helpers."""

from carton.core.install_state import (
    is_double_bound,
    is_my_tools,
    is_pure_local,
    is_registry_installed,
)


def _registry_only():
    return {"source": "registry", "path": "packages/a/b"}


def _double_bound():
    return {
        "source": "registry",
        "path": "packages/a/b",
        "local_path": "/tmp/source",
    }


def _pure_local():
    return {"source": "local", "local_path": "/tmp/source"}


class TestIsMyTools:
    def test_pure_local_is_my_tools(self):
        assert is_my_tools(_pure_local())

    def test_double_bound_is_my_tools(self):
        assert is_my_tools(_double_bound())

    def test_registry_only_is_not_my_tools(self):
        assert not is_my_tools(_registry_only())

    def test_empty_or_none_is_false(self):
        assert not is_my_tools(None)
        assert not is_my_tools({})


class TestIsRegistryInstalled:
    def test_registry_only(self):
        assert is_registry_installed(_registry_only())

    def test_double_bound(self):
        assert is_registry_installed(_double_bound())

    def test_pure_local_is_not(self):
        assert not is_registry_installed(_pure_local())

    def test_registry_without_path_is_not(self):
        # Demoted entries (path popped) shouldn't qualify as installed.
        entry = {"source": "registry"}
        assert not is_registry_installed(entry)


class TestIsPureLocal:
    def test_pure_local(self):
        assert is_pure_local(_pure_local())

    def test_double_bound_is_not(self):
        assert not is_pure_local(_double_bound())

    def test_registry_only_is_not(self):
        assert not is_pure_local(_registry_only())


class TestIsDoubleBound:
    def test_double_bound(self):
        assert is_double_bound(_double_bound())

    def test_registry_only_is_not(self):
        assert not is_double_bound(_registry_only())

    def test_pure_local_is_not(self):
        assert not is_double_bound(_pure_local())
