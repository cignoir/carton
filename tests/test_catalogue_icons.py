"""Tests for the catalogue icon storage helpers."""

import os
import zipfile

import pytest

from carton.core.catalogue_icons import (
    copy_icon_to_catalogue,
    is_icon_file,
    normalise_icon_for_storage,
    rebuild_icons_archive,
)


# --- is_icon_file -----------------------------------------------------------

def test_is_icon_file_accepts_existing_absolute_png(tmp_path):
    png = tmp_path / "icon.png"
    png.write_bytes(b"fake")
    assert is_icon_file(str(png)) is True


def test_is_icon_file_rejects_missing_path(tmp_path):
    assert is_icon_file(str(tmp_path / "nope.png")) is False


def test_is_icon_file_rejects_relative_path():
    assert is_icon_file("icon.png") is False


def test_is_icon_file_rejects_non_image_extension(tmp_path):
    f = tmp_path / "icon.txt"
    f.write_text("x")
    assert is_icon_file(str(f)) is False


@pytest.mark.parametrize("value", ["", None, "@auto", 42, "🔧"])
def test_is_icon_file_rejects_non_path_values(value):
    assert is_icon_file(value) is False


# --- normalise_icon_for_storage ---------------------------------------------

def test_normalise_returns_none_for_empty():
    assert normalise_icon_for_storage("") is None
    assert normalise_icon_for_storage(None) is None


def test_normalise_returns_basename_for_absolute_path(tmp_path):
    png = tmp_path / "MyTool.png"
    png.write_bytes(b"x")
    assert normalise_icon_for_storage(str(png)) == "MyTool.png"


def test_normalise_passes_through_emoji_and_literals():
    assert normalise_icon_for_storage("🔧") == "🔧"
    assert normalise_icon_for_storage("@auto") == "@auto"
    assert normalise_icon_for_storage("MyTool.png") == "MyTool.png"


# --- copy_icon_to_catalogue -------------------------------------------------

def test_copy_icon_creates_icons_dir_and_copies_file(tmp_path):
    src = tmp_path / "source.png"
    src.write_bytes(b"PNGDATA")
    catalogue = tmp_path / "cat"
    catalogue.mkdir()

    copy_icon_to_catalogue(str(src), "Renamed.png", str(catalogue))

    dest = catalogue / "icons" / "Renamed.png"
    assert dest.exists()
    assert dest.read_bytes() == b"PNGDATA"


def test_copy_icon_preserves_arbitrary_dest_filename(tmp_path):
    src = tmp_path / "source.png"
    src.write_bytes(b"x")
    catalogue = tmp_path / "cat"
    catalogue.mkdir()

    copy_icon_to_catalogue(str(src), "日本語.png", str(catalogue))

    assert (catalogue / "icons" / "日本語.png").exists()


# --- rebuild_icons_archive --------------------------------------------------

def test_rebuild_archive_no_op_if_dir_missing(tmp_path):
    catalogue = tmp_path / "cat"
    catalogue.mkdir()
    # Should not raise, should not create icons.zip.
    rebuild_icons_archive(str(catalogue))
    assert not (catalogue / "icons.zip").exists()


def test_rebuild_archive_no_op_if_no_pngs(tmp_path):
    catalogue = tmp_path / "cat"
    (catalogue / "icons").mkdir(parents=True)
    (catalogue / "icons" / "readme.txt").write_text("x")

    rebuild_icons_archive(str(catalogue))

    assert not (catalogue / "icons.zip").exists()


def test_rebuild_archive_includes_all_pngs(tmp_path):
    catalogue = tmp_path / "cat"
    icons = catalogue / "icons"
    icons.mkdir(parents=True)
    (icons / "a.png").write_bytes(b"A")
    (icons / "b.png").write_bytes(b"BB")
    (icons / "skip.txt").write_text("x")

    rebuild_icons_archive(str(catalogue))

    archive = catalogue / "icons.zip"
    assert archive.exists()
    with zipfile.ZipFile(str(archive), "r") as zf:
        names = sorted(zf.namelist())
    assert names == ["a.png", "b.png"]


def test_rebuild_archive_case_insensitive_png_detection(tmp_path):
    catalogue = tmp_path / "cat"
    icons = catalogue / "icons"
    icons.mkdir(parents=True)
    (icons / "Upper.PNG").write_bytes(b"x")

    rebuild_icons_archive(str(catalogue))

    archive = catalogue / "icons.zip"
    assert archive.exists()
    with zipfile.ZipFile(str(archive), "r") as zf:
        assert "Upper.PNG" in zf.namelist()
