"""Tests for the refresh-from-disk helper.

The EditDialog uses :func:`carton.core.refresh_from_disk.read_manifest`
to pull the latest values out of the source ``package.json`` (or the
``.carton.json`` sidecar) so the user can resync ``installed.json``
without remove-and-re-register. These tests pin the read + diff
contract so the UI always gets back something it can shove into form
fields.
"""

import json

import pytest

from carton.core.refresh_from_disk import (
    REFRESHABLE_FIELDS,
    RefreshError,
    diff_fields,
    read_manifest,
)


# ---------------------------------------------------------------------------
# read_manifest — folder packages
# ---------------------------------------------------------------------------


def _write_pkg_json(folder, data):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "package.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8",
    )


def test_folder_with_package_json_is_read(tmp_path):
    _write_pkg_json(tmp_path, {"name": "foo", "version": "1.2.3"})
    out = read_manifest(str(tmp_path), is_folder=True)
    assert out == {"name": "foo", "version": "1.2.3"}


def test_folder_without_package_json_returns_none(tmp_path):
    """Folder exists but has no manifest — caller decides whether to
    surface that as a soft "nothing to refresh" or a hard error.
    Returning None keeps the helper out of UX policy."""
    assert read_manifest(str(tmp_path), is_folder=True) is None


def test_missing_path_raises(tmp_path):
    nope = tmp_path / "does-not-exist"
    with pytest.raises(RefreshError, match="no longer exists"):
        read_manifest(str(nope), is_folder=True)


def test_unset_local_path_raises(tmp_path):
    """An empty local_path is a configuration error worth surfacing —
    the user expected something to refresh from."""
    with pytest.raises(RefreshError, match="no longer exists"):
        read_manifest("", is_folder=True)


def test_malformed_json_raises_loudly(tmp_path):
    (tmp_path / "package.json").write_text("not json {", encoding="utf-8")
    with pytest.raises(RefreshError, match="Couldn't read package.json"):
        read_manifest(str(tmp_path), is_folder=True)


def test_non_object_json_raises(tmp_path):
    (tmp_path / "package.json").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(RefreshError, match="must be a JSON object"):
        read_manifest(str(tmp_path), is_folder=True)


def test_localized_description_round_trips(tmp_path):
    """The description field can be a string or a {locale: str} dict —
    refresh shouldn't flatten that into a string."""
    payload = {
        "name": "foo",
        "description": {"en": "Hello", "ja": "やあ"},
    }
    _write_pkg_json(tmp_path, payload)
    out = read_manifest(str(tmp_path), is_folder=True)
    assert out["description"] == {"en": "Hello", "ja": "やあ"}


# ---------------------------------------------------------------------------
# read_manifest — single-file (sidecar)
# ---------------------------------------------------------------------------


def test_sidecar_is_read_for_single_file(tmp_path):
    script = tmp_path / "tool.py"
    script.write_text("def show(): pass\n", encoding="utf-8")
    sidecar = tmp_path / "tool.py.carton.json"
    sidecar.write_text(
        json.dumps({"name": "tool", "version": "0.5.0"}),
        encoding="utf-8",
    )
    out = read_manifest(str(script), is_folder=False)
    assert out == {"name": "tool", "version": "0.5.0"}


def test_single_file_without_sidecar_returns_none(tmp_path):
    script = tmp_path / "tool.py"
    script.write_text("def show(): pass\n", encoding="utf-8")
    assert read_manifest(str(script), is_folder=False) is None


# ---------------------------------------------------------------------------
# diff_fields
# ---------------------------------------------------------------------------


def test_diff_reports_changed_refreshable_fields():
    current = {"version": "1.0.0", "icon": "🔧", "author": "alice"}
    fresh = {"version": "1.1.0", "icon": "🔧", "author": "bob"}
    out = diff_fields(current, fresh)
    assert out == {
        "version": ("1.0.0", "1.1.0"),
        "author": ("alice", "bob"),
    }


def test_diff_ignores_non_refreshable_fields():
    """Refreshing must not be allowed to rename a package — namespace
    and name aren't in REFRESHABLE_FIELDS, so a manifest with different
    values shouldn't show up as a change."""
    assert "namespace" not in REFRESHABLE_FIELDS
    assert "name" not in REFRESHABLE_FIELDS
    current = {"namespace": "old", "name": "old"}
    fresh = {"namespace": "new", "name": "new"}
    assert diff_fields(current, fresh) == {}


def test_diff_skips_fields_absent_from_fresh():
    """If the manifest doesn't carry a field, refresh must not erase
    the installed value — protective against partial manifests."""
    current = {"version": "1.0.0", "author": "alice"}
    fresh = {"version": "1.1.0"}  # author absent
    out = diff_fields(current, fresh)
    assert out == {"version": ("1.0.0", "1.1.0")}
    assert "author" not in out


def test_diff_returns_empty_when_identical():
    payload = {"version": "1.0.0", "author": "alice", "icon": "🔧"}
    assert diff_fields(payload, dict(payload)) == {}


def test_diff_handles_dict_description_change():
    current = {"description": "Old"}
    fresh = {"description": {"en": "New", "ja": "新しい"}}
    out = diff_fields(current, fresh)
    assert "description" in out
    assert out["description"] == ("Old", {"en": "New", "ja": "新しい"})
