"""Tests for ``carton.core.catalogue_lint``."""

import json
import os

import pytest

from carton.core.catalogue_lint import lint_catalogue
from carton.core.lint import SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO


def _write_catalogue(tmp_path, packages=None, **fields):
    """Helper to materialise a v5.0 catalogue.json."""
    data = {
        "schema_version": "5.0",
        "catalogue_id": "11111111-2222-3333-4444-555555555555",
        "display_name": "test catalogue",
        "packages": packages or {},
    }
    data.update(fields)
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Path / parse handling
# ---------------------------------------------------------------------------

def test_lint_nonexistent_path_errors():
    result = lint_catalogue("/no/such/catalogue.json")
    assert result.has_errors()
    assert result.errors[0].rule == "path_not_found"


def test_lint_malformed_json_errors(tmp_path):
    path = tmp_path / "catalogue.json"
    path.write_text("{not valid", encoding="utf-8")
    result = lint_catalogue(str(path))
    assert result.has_errors()
    assert result.errors[0].rule == "catalogue_json_syntax"


# ---------------------------------------------------------------------------
# Empty / minimal
# ---------------------------------------------------------------------------

def test_lint_empty_catalogue_passes(tmp_path):
    path = _write_catalogue(tmp_path)
    result = lint_catalogue(path)
    assert not result.has_errors()
    rules = {i.rule for i in result.issues}
    assert "empty_catalogue" in rules


def test_lint_missing_catalogue_id_warns(tmp_path):
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps({
        "schema_version": "5.0",
        "display_name": "no-id",
        "packages": {},
    }), encoding="utf-8")
    result = lint_catalogue(str(path))
    rules = {i.rule for i in result.warnings}
    assert "catalogue_id_missing" in rules


# ---------------------------------------------------------------------------
# Embedded origin
# ---------------------------------------------------------------------------

def test_lint_embedded_with_existing_zip_passes(tmp_path):
    zip_path = tmp_path / "packages" / "ns" / "tool" / "1.0.0" / "tool-1.0.0.zip"
    os.makedirs(os.path.dirname(str(zip_path)), exist_ok=True)
    zip_path.write_bytes(b"fake zip")

    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {
                "type": "embedded",
                "latest_version": "1.0.0",
                "versions": {
                    "1.0.0": {
                        "download_url": "packages/ns/tool/1.0.0/tool-1.0.0.zip",
                        "sha256": "a" * 64,
                        "size_bytes": 100,
                        "maya_versions": ["2025"],
                        "released_at": "2026-05-01",
                    },
                },
            },
        },
    })
    result = lint_catalogue(path)
    rules = {i.rule for i in result.errors}
    assert "embedded_zip_missing" not in rules


def test_lint_embedded_missing_zip_errors(tmp_path):
    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {
                "type": "embedded",
                "latest_version": "1.0.0",
                "versions": {
                    "1.0.0": {
                        "download_url": "packages/ns/tool/1.0.0/missing.zip",
                        "sha256": "a" * 64,
                        "size_bytes": 100,
                        "maya_versions": ["2025"],
                        "released_at": "2026-05-01",
                    },
                },
            },
        },
    })
    result = lint_catalogue(path)
    rules = {i.rule for i in result.errors}
    assert "embedded_zip_missing" in rules


def test_lint_embedded_no_sha256_warns(tmp_path):
    zip_path = tmp_path / "packages" / "ns" / "tool" / "1.0.0" / "tool-1.0.0.zip"
    os.makedirs(os.path.dirname(str(zip_path)), exist_ok=True)
    zip_path.write_bytes(b"fake")

    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {
                "type": "embedded",
                "latest_version": "1.0.0",
                "versions": {
                    "1.0.0": {
                        "download_url": "packages/ns/tool/1.0.0/tool-1.0.0.zip",
                        "size_bytes": 100,
                        "maya_versions": ["2025"],
                        "released_at": "2026-05-01",
                    },
                },
            },
        },
    })
    result = lint_catalogue(path)
    rules = {i.rule for i in result.warnings}
    assert "embedded_sha256_missing" in rules


def test_lint_embedded_no_versions_errors(tmp_path):
    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {"type": "embedded", "versions": {}},
        },
    })
    result = lint_catalogue(path)
    rules = {i.rule for i in result.errors}
    assert "embedded_no_versions" in rules


# ---------------------------------------------------------------------------
# github / url / local origins
# ---------------------------------------------------------------------------

def test_lint_github_origin_passes_offline(tmp_path):
    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {"type": "github", "repo": "ns/tool"},
        },
    })
    result = lint_catalogue(path)
    assert not result.has_errors()


def test_lint_github_origin_missing_repo_errors(tmp_path):
    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {"type": "github"},
        },
    })
    result = lint_catalogue(path)
    rules = {i.rule for i in result.errors}
    assert "github_repo_missing" in rules


def test_lint_url_origin_missing_url_errors(tmp_path):
    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {"type": "url"},
        },
    })
    result = lint_catalogue(path)
    rules = {i.rule for i in result.errors}
    assert "url_missing" in rules


def test_lint_local_origin_existing_path_passes(tmp_path):
    target = tmp_path / "tools" / "tool"
    target.mkdir(parents=True)

    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {"type": "local", "path": str(target)},
        },
    })
    result = lint_catalogue(path)
    assert not result.has_errors()


def test_lint_local_origin_missing_path_warns(tmp_path):
    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {"type": "local", "path": "/no/such/path/abc"},
        },
    })
    result = lint_catalogue(path)
    rules = {i.rule for i in result.warnings}
    assert "local_path_unreachable" in rules


# ---------------------------------------------------------------------------
# Unknown origin type
# ---------------------------------------------------------------------------

def test_lint_unknown_origin_type_errors(tmp_path):
    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {"type": "magicalpony"},
        },
    })
    result = lint_catalogue(path)
    rules = {i.rule for i in result.errors}
    assert "origin_type_unknown" in rules


def test_lint_origin_type_missing_errors(tmp_path):
    path = _write_catalogue(tmp_path, packages={
        "ns/tool": {
            "origin": {},
        },
    })
    result = lint_catalogue(path)
    rules = {i.rule for i in result.errors}
    assert "origin_type_missing" in rules
