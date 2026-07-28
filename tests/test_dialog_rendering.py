"""Construction and read-out coverage for the remaining dialogs.

These were the last UI modules with no test at all. They are mostly
layout, but each one reads a package dict and decides what to put in
front of the user — which version is installed, whether an action is
even offered — and that logic silently stops matching the data model
whenever the model moves.

Nothing here asserts on appearance. The assertions are on what the
dialog concluded from its input.
"""

import pytest

pytest.importorskip("pytestqt")

from carton.ui.compat import QtWidgets
from carton.ui.edit_dialog import EditDialog
from carton.ui.i18n import t
from carton.ui.package_detail import PackageDetailPanel
from carton.ui.publish_confirm_dialog import PublishConfirmDialog
from carton.ui.version_history_dialog import VersionHistoryDialog


PKG_ID = "acme/rigger"


def _catalogue_data(**extra):
    data = {
        "namespace": "acme",
        "name": "rigger",
        "display_name": "Rigger",
        "type": "python_package",
        "description": "Rigs things",
        "author": "acme",
        "latest_version": "1.2.0",
        "versions": {
            "1.0.0": {"sha256": "0" * 64, "size_bytes": 1024},
            "1.1.0": {"sha256": "1" * 64, "size_bytes": 2048},
            "1.2.0": {"sha256": "2" * 64, "size_bytes": 4096},
        },
    }
    data.update(extra)
    return data


def _texts(widget):
    return [w.text() for w in widget.findChildren(QtWidgets.QLabel)]


def _button_labels(widget):
    return [b.text() for b in widget.findChildren(QtWidgets.QPushButton)]


class TestPackageDetailPanel:
    def test_constructs_empty(self, qtbot):
        panel = PackageDetailPanel()
        qtbot.addWidget(panel)
        assert panel is not None

    def test_shows_the_display_name(self, qtbot):
        panel = PackageDetailPanel()
        qtbot.addWidget(panel)

        panel.show_package(PKG_ID, _catalogue_data())

        assert "Rigger" in _texts(panel)

    def test_falls_back_to_the_pkg_id_without_a_display_name(self, qtbot):
        panel = PackageDetailPanel()
        qtbot.addWidget(panel)
        data = _catalogue_data()
        del data["display_name"]

        panel.show_package(PKG_ID, data)

        assert PKG_ID in _texts(panel)

    def test_offers_install_when_not_installed(self, qtbot):
        panel = PackageDetailPanel()
        qtbot.addWidget(panel)

        panel.show_package(PKG_ID, _catalogue_data(), installed_version=None)

        assert t("install") in _button_labels(panel)

    def test_offers_uninstall_once_installed(self, qtbot):
        panel = PackageDetailPanel()
        qtbot.addWidget(panel)

        panel.show_package(PKG_ID, _catalogue_data(),
                           installed_version="1.2.0")

        assert t("uninstall") in _button_labels(panel)

    def test_survives_a_package_with_no_versions(self, qtbot):
        """A catalogue entry can be projected before any release exists."""
        panel = PackageDetailPanel()
        qtbot.addWidget(panel)

        panel.show_package(PKG_ID, {"name": "rigger", "display_name": "R"})

        assert "R" in _texts(panel)

    def test_back_button_emits(self, qtbot):
        panel = PackageDetailPanel()
        qtbot.addWidget(panel)
        panel.show_package(PKG_ID, _catalogue_data())
        back = next(b for b in panel.findChildren(QtWidgets.QPushButton)
                    if b.text() == t("back"))

        with qtbot.waitSignal(panel.back_requested):
            back.click()


class TestVersionHistoryDialog:
    def test_lists_every_published_version(self, qtbot):
        dlg = VersionHistoryDialog(PKG_ID, _catalogue_data(), "1.0.0")
        qtbot.addWidget(dlg)

        blob = " ".join(_texts(dlg))
        for version in ("1.0.0", "1.1.0", "1.2.0"):
            assert version in blob

    def test_versions_are_ordered_numerically(self, qtbot):
        """Lexicographic order breaks as soon as a component hits two digits."""
        data = _catalogue_data(
            latest_version="1.10.0",
            versions={v: {} for v in ("1.9.0", "1.10.0", "1.2.0")},
        )
        dlg = VersionHistoryDialog(PKG_ID, data, "1.2.0")
        qtbot.addWidget(dlg)

        ordered = dlg._sorted_versions(data["versions"].keys())
        assert list(ordered)[0] == "1.10.0"

    def test_no_version_chosen_until_the_user_picks_one(self, qtbot):
        dlg = VersionHistoryDialog(PKG_ID, _catalogue_data(), "1.0.0")
        qtbot.addWidget(dlg)

        assert dlg.chosen_version() is None

    def test_empty_history_still_constructs(self, qtbot):
        dlg = VersionHistoryDialog(PKG_ID, {"display_name": "R"}, "")
        qtbot.addWidget(dlg)

        assert dlg.chosen_version() is None


class TestPublishConfirmDialog:
    def test_names_the_package_and_target(self, qtbot):
        dlg = PublishConfirmDialog("Rigger", "1.2.0", "Studio")
        qtbot.addWidget(dlg)

        blob = " ".join(_texts(dlg))
        assert "Rigger" in blob
        assert "1.2.0" in blob
        assert "Studio" in blob

    def test_release_notes_start_empty(self, qtbot):
        dlg = PublishConfirmDialog("Rigger", "1.2.0", "Studio")
        qtbot.addWidget(dlg)

        assert dlg.release_notes() == ""

    def test_release_notes_are_read_back(self, qtbot):
        dlg = PublishConfirmDialog("Rigger", "1.2.0", "Studio")
        qtbot.addWidget(dlg)
        notes = next(iter(dlg.findChildren(QtWidgets.QPlainTextEdit)), None) \
            or next(iter(dlg.findChildren(QtWidgets.QTextEdit)))
        notes.setPlainText("fixed the thing")

        assert dlg.release_notes() == "fixed the thing"

    def test_embed_source_path_is_a_bool(self, qtbot):
        dlg = PublishConfirmDialog("Rigger", "1.2.0", "Studio")
        qtbot.addWidget(dlg)

        assert isinstance(dlg.embed_source_path(), bool)


def _installed(**extra):
    data = {
        "namespace": "acme",
        "name": "rigger",
        "display_name": "Rigger",
        "version": "1.0.0",
        "author": "acme",
        "type": "python_package",
        "source": "local",
        "local_path": "/tmp/rigger",
        "is_folder": True,
        "icon": "🔧",
        "description": "Rigs things",
        "entry_point": {"type": "python", "module": "rigger",
                        "function": "show"},
    }
    data.update(extra)
    return data


class TestEditDialog:
    def test_fields_are_populated_from_the_entry(self, qtbot):
        dlg = EditDialog(PKG_ID, _installed())
        qtbot.addWidget(dlg)

        assert dlg._name_input.text() == "Rigger"
        assert dlg._ver_input.text() == "1.0.0"

    def test_namespace_is_editable_while_unpublished(self, qtbot):
        dlg = EditDialog(PKG_ID, _installed(), published_catalogues=[])
        qtbot.addWidget(dlg)

        assert not dlg._namespace_input.isReadOnly()

    def test_namespace_locks_once_published(self, qtbot):
        """Changing it after publish would orphan the published identity."""
        dlg = EditDialog(PKG_ID, _installed(),
                         published_catalogues=[{"name": "Studio"}])
        qtbot.addWidget(dlg)

        assert dlg._namespace_input.isReadOnly()

    def test_save_returns_the_edited_values(self, qtbot):
        dlg = EditDialog(PKG_ID, _installed())
        qtbot.addWidget(dlg)
        dlg._name_input.setText("Renamed Rigger")
        dlg._ver_input.setText("1.1.0")

        dlg._on_save()

        result = dlg.get_result()
        assert result["action"] == "save"
        assert result["display_name"] == "Renamed Rigger"
        assert result["version"] == "1.1.0"

    def test_no_result_before_any_action(self, qtbot):
        dlg = EditDialog(PKG_ID, _installed())
        qtbot.addWidget(dlg)

        assert dlg.get_result() is None
