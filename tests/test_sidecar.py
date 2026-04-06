"""Tests for the single-file sidecar helper."""

import os
import tempfile

from carton.core.sidecar import (
    SIDECAR_SUFFIX,
    sidecar_path_for,
    read_sidecar,
    write_sidecar,
    merge_sidecar,
)


def test_sidecar_path_for_includes_extension():
    assert sidecar_path_for("/tmp/foo.mel") == "/tmp/foo.mel" + SIDECAR_SUFFIX


def test_read_missing_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        assert read_sidecar(os.path.join(tmp, "absent.py")) is None


def test_write_then_read_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "rename.mel")
        with open(target, "w") as f:
            f.write("// mel")
        write_sidecar(target, {"namespace": "mystudio", "name": "rename"})
        data = read_sidecar(target)
        assert data == {"namespace": "mystudio", "name": "rename"}


def test_merge_preserves_existing_fields():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "x.py")
        with open(target, "w") as f:
            f.write("# py")
        write_sidecar(target, {"namespace": "ns", "name": "x", "author": "alice"})
        merge_sidecar(target, {"version": "1.2.0"})
        data = read_sidecar(target)
        assert data["author"] == "alice"
        assert data["version"] == "1.2.0"
