"""Tests for ``carton-maya {package,catalogue} schema`` commands.

The output is intended to be valid JSON that an IDE can drop straight
into a JSON Schema configuration. We assert structural fidelity only —
the actual schema content lives in carton/data/schemas/ and is exercised
by the lint tests.
"""

import json
import sys
from unittest import mock

import pytest

from carton.cli import main


def _run(argv):
    with mock.patch.object(sys, "argv", argv):
        main()


def test_package_schema_emits_valid_json(capsys):
    _run(["carton-maya", "package", "schema"])
    out = capsys.readouterr().out
    schema = json.loads(out)
    assert schema.get("title") == "Carton Package Metadata"
    assert "properties" in schema


def test_catalogue_schema_emits_valid_json(capsys):
    _run(["carton-maya", "catalogue", "schema"])
    out = capsys.readouterr().out
    schema = json.loads(out)
    # Either v4.0 ("Carton Registry ...") or v5.0 ("Carton Catalogue ...");
    # both are valid since migrations can read either.
    assert "title" in schema
    assert "properties" in schema
