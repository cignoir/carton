"""A catalogue that fails to load has to say so.

Until this existed, a subscribed catalogue whose host didn't answer just
disappeared: its packages weren't in the merged dict, nothing on screen
mentioned it, and the only trace was a line in the log. From the user's
seat that is indistinguishable from Carton having dropped the
subscription — which is exactly how it was reported.
"""

import json
import os

import pytest

from carton.core.catalogue.client import CatalogueClient
from carton.core.catalogue.personal import PersonalCatalogue
from carton.core.config import CatalogueEntry, Config


def _client(tmp_path, entries):
    config = Config(install_dir=str(tmp_path / "home"), catalogues=entries)
    return CatalogueClient(config, personal_catalogue=PersonalCatalogue())


def _write_catalogue(path, pkg_id="acme/tool"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "schema_version": "5.0",
            "catalogue_id": "11111111-2222-3333-4444-555555555555",
            "display_name": "Good One",
            "packages": {
                pkg_id: {
                    "origin": {
                        "type": "embedded",
                        "latest_version": "1.0.0",
                        "versions": {
                            "1.0.0": {
                                "maya_versions": ["2024"],
                                "download_url": "packages/x.zip",
                                "released_at": "2026-01-01T00:00:00Z",
                            },
                        },
                    },
                    "namespace": "acme",
                    "name": "tool",
                },
            },
        }, f)


class TestFetchErrorsAreRecorded:
    def test_clean_fetch_reports_no_errors(self, tmp_path):
        good = tmp_path / "catalogue.json"
        _write_catalogue(str(good))
        client = _client(tmp_path, [CatalogueEntry(str(good), display_name="Good One")])

        client.fetch()

        assert client.get_fetch_errors() == []
        assert "acme/tool" in client.get_packages()

    def test_missing_local_file_is_reported(self, tmp_path):
        missing = tmp_path / "nope" / "catalogue.json"
        client = _client(tmp_path, [CatalogueEntry(str(missing), display_name="Gone")])

        client.fetch()

        errors = client.get_fetch_errors()
        assert len(errors) == 1
        assert errors[0]["label"] == "Gone"
        assert errors[0]["reason"]

    def test_malformed_local_file_is_reported(self, tmp_path):
        broken = tmp_path / "catalogue.json"
        with open(str(broken), "w", encoding="utf-8") as f:
            f.write("{ not json")
        client = _client(tmp_path, [CatalogueEntry(str(broken), display_name="Broken")])

        client.fetch()

        assert [e["label"] for e in client.get_fetch_errors()] == ["Broken"]

    def test_one_failure_does_not_hide_the_other_catalogue(self, tmp_path):
        """The whole point: the good catalogue still loads, and the bad
        one is named rather than silently absent."""
        good = tmp_path / "catalogue.json"
        _write_catalogue(str(good))
        client = _client(tmp_path, [
            CatalogueEntry(str(good), display_name="Good One"),
            CatalogueEntry(str(tmp_path / "missing" / "catalogue.json"),
                           display_name="Missing One"),
        ])

        client.fetch()

        assert "acme/tool" in client.get_packages()
        assert [e["label"] for e in client.get_fetch_errors()] == ["Missing One"]

    def test_errors_reset_between_fetches(self, tmp_path):
        target = tmp_path / "catalogue.json"
        client = _client(tmp_path, [CatalogueEntry(str(target), display_name="Later")])

        client.fetch()
        assert client.get_fetch_errors()

        _write_catalogue(str(target))
        client.fetch()
        assert client.get_fetch_errors() == []

    def test_returned_list_is_a_copy(self, tmp_path):
        client = _client(tmp_path, [
            CatalogueEntry(str(tmp_path / "gone.json"), display_name="Gone"),
        ])
        client.fetch()

        client.get_fetch_errors().clear()

        assert len(client.get_fetch_errors()) == 1
