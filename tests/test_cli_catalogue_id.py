"""Smoke tests for ``python -m carton catalogue id [--stamp]``.

Drives the CLI via ``carton.cli.main()`` with a mocked ``sys.argv`` so
the test stays fast (no subprocess spawn) while still exercising the
parser dispatch.
"""

import json
import sys
from unittest import mock

import pytest

from carton.cli import main


def _write_catalogue(tmp_path, **fields):
    path = tmp_path / "catalogue.json"
    data = {"schema_version": "5.0", "packages": {}}
    data.update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _run(argv):
    with mock.patch.object(sys, "argv", argv):
        main()


def test_catalogue_id_prints_nothing_when_missing(tmp_path, capsys):
    path = _write_catalogue(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run(["carton", "catalogue", "id", path])
    assert exc.value.code == 2
    assert "(no catalogue_id)" in capsys.readouterr().out


def test_catalogue_id_prints_existing(tmp_path, capsys):
    rid = "11111111-2222-3333-4444-555555555555"
    path = _write_catalogue(tmp_path, catalogue_id=rid)
    _run(["carton", "catalogue", "id", path])
    assert rid in capsys.readouterr().out


def test_catalogue_id_stamps_when_missing(tmp_path, capsys):
    path = _write_catalogue(tmp_path)
    _run(["carton", "catalogue", "id", path, "--stamp"])
    out = capsys.readouterr().out
    assert "Stamped:" in out
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("catalogue_id"), "catalogue_id should be written"


def test_catalogue_id_stamp_is_idempotent(tmp_path, capsys):
    rid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    path = _write_catalogue(tmp_path, catalogue_id=rid)
    _run(["carton", "catalogue", "id", path, "--stamp"])
    out = capsys.readouterr().out
    assert "Already has catalogue_id" in out
    assert rid in out
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["catalogue_id"] == rid


def test_catalogue_id_rejects_pre_v5_file(tmp_path, capsys):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({
            "schema_version": "4.0",
            "registry_id": "11111111-2222-3333-4444-555555555555",
            "packages": {},
        }),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        _run(["carton", "catalogue", "id", str(path)])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "catalogue migrate" in out
