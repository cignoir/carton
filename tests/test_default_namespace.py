"""A namespace typed once should not have to be typed again.

Registering without one produces an entry that cannot be published
until it is edited, and almost everybody registers everything they own
under the same namespace — so the field was pure repetition with a
failure mode attached.
"""

import json

import pytest

from carton.core.config import Config


class TestConfigField:
    def test_defaults_to_empty(self):
        assert Config().default_namespace == ""

    def test_round_trips_through_disk(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = Config(install_dir=str(tmp_path / "data"))
        cfg.default_namespace = "mystudio"
        cfg.save(str(path))

        assert Config.load(str(path)).default_namespace == "mystudio"

    def test_serialised_into_config_json(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = Config(install_dir=str(tmp_path / "data"),
                     default_namespace="acme")
        cfg.save(str(path))

        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["default_namespace"] == "acme"

    def test_absent_key_loads_as_empty(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"catalogues": []}), encoding="utf-8")

        assert Config.load(str(path)).default_namespace == ""


pytest.importorskip("pytestqt")

from carton.ui.add_dialog import AddDialog  # noqa: E402
from carton.ui.settings_widgets import DefaultNamespaceSection  # noqa: E402


class TestAddDialogPrefill:
    def test_namespace_field_starts_prefilled(self, qtbot):
        dialog = AddDialog(default_namespace="mystudio")
        qtbot.addWidget(dialog)

        assert dialog._namespace_input.text() == "mystudio"

    def test_no_default_leaves_the_field_empty(self, qtbot):
        dialog = AddDialog()
        qtbot.addWidget(dialog)

        assert dialog._namespace_input.text() == ""

    def test_prefill_is_editable(self, qtbot):
        """A default is a starting point, not a constraint."""
        dialog = AddDialog(default_namespace="mystudio")
        qtbot.addWidget(dialog)

        dialog._namespace_input.setText("otherstudio")

        assert dialog._namespace_input.text() == "otherstudio"


class TestSettingsSection:
    def test_shows_the_configured_value(self, qtbot):
        cfg = Config(default_namespace="acme")
        section = DefaultNamespaceSection(cfg, lambda: None)
        qtbot.addWidget(section)

        assert section._input.text() == "acme"

    def test_editing_persists(self, qtbot):
        cfg = Config()
        saves = []
        section = DefaultNamespaceSection(cfg, lambda: saves.append(True))
        qtbot.addWidget(section)

        section._input.setText("mystudio")
        section._on_edited()

        assert cfg.default_namespace == "mystudio"
        assert saves == [True]

    def test_value_is_slugified_on_entry(self, qtbot):
        """Store what a package id would actually use.

        Otherwise the dialog silently rewrites the prefill and the user
        finds out at publish time that the two disagreed.
        """
        cfg = Config()
        section = DefaultNamespaceSection(cfg, lambda: None)
        qtbot.addWidget(section)

        section._input.setText("My Studio")
        section._on_edited()

        assert cfg.default_namespace == "my-studio"
        assert section._input.text() == "my-studio"

    def test_no_save_when_nothing_changed(self, qtbot):
        cfg = Config(default_namespace="acme")
        saves = []
        section = DefaultNamespaceSection(cfg, lambda: saves.append(True))
        qtbot.addWidget(section)

        section._on_edited()

        assert saves == []

    def test_clearing_the_field_is_persisted(self, qtbot):
        cfg = Config(default_namespace="acme")
        saves = []
        section = DefaultNamespaceSection(cfg, lambda: saves.append(True))
        qtbot.addWidget(section)

        section._input.setText("")
        section._on_edited()

        assert cfg.default_namespace == ""
        assert saves == [True]
