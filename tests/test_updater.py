"""Tests for Updater (registry vs installed version comparison)."""

import types

from carton.core.updater import Updater


def _client(packages):
    return types.SimpleNamespace(get_packages=lambda: packages)


def _mgr(installed):
    return types.SimpleNamespace(
        get_installed_packages=lambda: installed,
        get_installed_version=lambda pkg_id: (
            installed.get(pkg_id, {}).get("version")
        ),
    )


REG = {
    "acme/rig": {
        "name": "rig",
        "latest_version": "0.10.0",
        "versions": {"0.10.0": {"download_url": "u"}},
    },
}


def test_semver_update_detected_not_lexicographic():
    # 0.9.0 -> 0.10.0 is an update even though "0.9.0" > "0.10.0" as strings.
    installed = {"acme/rig": {"source": "registry", "version": "0.9.0",
                              "name": "rig"}}
    updates = Updater(_client(REG), _mgr(installed)).check_all_updates()
    assert len(updates) == 1
    assert updates[0].latest_version == "0.10.0"
    assert updates[0].current_version == "0.9.0"


def test_up_to_date_yields_nothing():
    installed = {"acme/rig": {"source": "registry", "version": "0.10.0"}}
    assert Updater(_client(REG), _mgr(installed)).check_all_updates() == []


def test_pure_my_tools_entries_are_skipped():
    installed = {"acme/rig": {"source": "local", "version": "0.1.0"}}
    assert Updater(_client(REG), _mgr(installed)).check_all_updates() == []


def test_unknown_registry_entry_is_skipped():
    installed = {"acme/gone": {"source": "registry", "version": "1.0.0"}}
    assert Updater(_client(REG), _mgr(installed)).check_all_updates() == []


def test_unparseable_version_is_skipped():
    installed = {"acme/rig": {"source": "registry", "version": "not-semver"}}
    assert Updater(_client(REG), _mgr(installed)).check_all_updates() == []


def test_check_update_single_package():
    installed = {"acme/rig": {"source": "registry", "version": "0.9.0"}}
    info = Updater(_client(REG), _mgr(installed)).check_update("acme/rig")
    assert info is not None
    assert info.pkg_id == "acme/rig"
    assert info.version_info == {"download_url": "u"}
    assert Updater(_client(REG), _mgr(installed)).check_update("x/y") is None
