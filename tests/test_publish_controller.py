"""Coverage for the publish state machine's decision points.

PublishController is the largest thing in the UI layer and it drives
the only flow that writes into a catalogue other people subscribe to.
Its branches — where a publish goes, whether it is allowed to proceed,
and what identity it goes out under — decide what other machines end up
installing, and every one of them sits behind a modal dialog that no
other test opens.

The version-conflict branch lives in its own module; this one covers
target dispatch, the namespace rescue path, the home-catalogue
mismatch guard, and the published-to badge map.
"""

import json
import types

import pytest

pytest.importorskip("pytestqt")

from carton.ui.compat import QtWidgets
import carton.ui._publish_controller as pc_module
from carton.ui._publish_controller import PublishController


PKG_ID = "acme/rigger"


def _catalogue(label="Studio", path="/tmp/studio/catalogue.json",
               catalogue_id="", is_remote=False):
    return types.SimpleNamespace(
        label=label, path=path, catalogue_id=catalogue_id,
        is_remote=is_remote,
        to_home_origin_meta=lambda: {"type": "embedded",
                                     "catalogue_name": label},
    )


class _StubInstallManager:
    def __init__(self, packages=None):
        self.packages = packages or {}
        self.updates = []

    def get_installed_packages(self):
        return self.packages

    def get_package(self, pkg_id):
        return self.packages.get(pkg_id)

    def update_package_fields(self, pkg_id, fields):
        if pkg_id not in self.packages:
            return False
        self.packages[pkg_id].update(fields)
        self.updates.append((pkg_id, dict(fields)))
        return True

    def rekey_package(self, old_id, new_id, fields=None):
        return True


class _StubWindow(QtWidgets.QWidget):
    def __init__(self, catalogues=(), packages=None):
        super().__init__()
        self._config = types.SimpleNamespace(catalogues=list(catalogues))
        self._install_manager = _StubInstallManager(packages)
        self._publisher = types.SimpleNamespace(
            publish=lambda *a, **k: {"id": PKG_ID, "namespace": "acme",
                                     "name": "rigger", "warnings": []},
            find_published_catalogues=lambda pkg_id: [],
        )
        self._card_layout = QtWidgets.QVBoxLayout()
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1


def _pkg_data(**extra):
    data = {"name": "rigger", "namespace": "acme", "version": "1.0.0",
            "display_name": "Rigger", "type": "python_package"}
    data.update(extra)
    return data


@pytest.fixture
def window(qtbot):
    def _make(catalogues=(), packages=None):
        w = _StubWindow(catalogues, packages)
        qtbot.addWidget(w)
        return w, PublishController(w)
    return _make


class TestTargetDispatch:
    """``_pick_target`` maps dialog exit codes onto publish destinations.

    The codes are bare integers set by lambdas on each button, so a
    reordering would silently send a publish somewhere else.
    """

    def _with_dialog_result(self, monkeypatch, code, selected=None):
        class _FakeDialog:
            def __init__(self, config, parent=None):
                pass

            def exec_(self):
                return code

            @property
            def selected_catalogue(self):
                return selected

        monkeypatch.setattr(pc_module, "_PublishTargetDialog", _FakeDialog)

    def test_dropdown_selection_returns_the_catalogue(self, window,
                                                      monkeypatch):
        entry = _catalogue()
        self._with_dialog_result(monkeypatch, 1, selected=entry)
        _w, ctl = window()

        assert ctl._pick_target(_pkg_data()) == ("embedded", entry)

    def test_dropdown_with_nothing_selected_cancels(self, window, monkeypatch):
        self._with_dialog_result(monkeypatch, 1, selected=None)
        _w, ctl = window()

        assert ctl._pick_target(_pkg_data()) is None

    def test_create_new_routes_through_the_window_helper(self, window,
                                                         monkeypatch):
        entry = _catalogue("Fresh")
        self._with_dialog_result(monkeypatch, 2)
        w, ctl = window()
        w._create_new_catalogue = lambda paired_remote=None: entry

        assert ctl._pick_target(_pkg_data()) == ("embedded", entry)

    def test_add_existing_routes_through_the_window_helper(self, window,
                                                           monkeypatch):
        entry = _catalogue("Existing")
        self._with_dialog_result(monkeypatch, 3)
        w, ctl = window()
        w._add_existing_catalogue = lambda paired_remote=None: entry

        assert ctl._pick_target(_pkg_data()) == ("embedded", entry)

    def test_github_branch_prompts_for_a_repo(self, window, monkeypatch):
        self._with_dialog_result(monkeypatch, 4)
        w, ctl = window()
        monkeypatch.setattr(ctl, "_prompt_github_repo",
                            lambda pkg_data: "acme/tools")

        assert ctl._pick_target(_pkg_data()) == ("github", "acme/tools")

    def test_cancel_returns_none(self, window, monkeypatch):
        self._with_dialog_result(monkeypatch, 0)
        _w, ctl = window()

        assert ctl._pick_target(_pkg_data()) is None


class TestGithubRepoPrompt:
    def _answer(self, monkeypatch, text, ok=True):
        monkeypatch.setattr(
            pc_module.QtWidgets.QInputDialog, "getText",
            staticmethod(lambda *a, **k: (text, ok)),
        )

    def test_accepts_owner_slash_repo(self, window, monkeypatch):
        self._answer(monkeypatch, "acme/tools")
        _w, ctl = window()

        assert ctl._prompt_github_repo(_pkg_data()) == "acme/tools"

    def test_strips_surrounding_slashes_and_space(self, window, monkeypatch):
        self._answer(monkeypatch, "  /acme/tools/  ")
        _w, ctl = window()

        assert ctl._prompt_github_repo(_pkg_data()) == "acme/tools"

    def test_rejects_a_bare_name(self, window, monkeypatch):
        self._answer(monkeypatch, "tools")
        _w, ctl = window()
        monkeypatch.setattr(pc_module.QtWidgets.QMessageBox, "warning",
                            staticmethod(lambda *a, **k: None))

        assert ctl._prompt_github_repo(_pkg_data()) == ""

    def test_rejects_a_full_url(self, window, monkeypatch):
        self._answer(monkeypatch, "https://github.com/acme/tools")
        _w, ctl = window()
        monkeypatch.setattr(pc_module.QtWidgets.QMessageBox, "warning",
                            staticmethod(lambda *a, **k: None))

        assert ctl._prompt_github_repo(_pkg_data()) == ""

    def test_cancel_returns_empty(self, window, monkeypatch):
        self._answer(monkeypatch, "acme/tools", ok=False)
        _w, ctl = window()

        assert ctl._prompt_github_repo(_pkg_data()) == ""

    def test_prefills_from_a_github_home_origin(self, window, monkeypatch):
        seen = {}

        def _get_text(parent, title, label, mode, default):
            seen["default"] = default
            return ("acme/tools", True)

        monkeypatch.setattr(pc_module.QtWidgets.QInputDialog, "getText",
                            staticmethod(_get_text))
        _w, ctl = window()

        ctl._prompt_github_repo(_pkg_data(
            home_origin={"type": "github", "repo": "acme/tools"}))

        assert seen["default"] == "acme/tools"


class TestNamespaceRescue:
    """Pre-v0.5 registrations can reach publish without a namespace."""

    def test_existing_namespace_is_used_without_prompting(self, window,
                                                          monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("should not prompt")

        monkeypatch.setattr(pc_module.QtWidgets.QInputDialog, "getText",
                            staticmethod(_boom))
        _w, ctl = window()

        assert ctl._ensure_namespace(PKG_ID, _pkg_data()) == "acme"

    def test_prompted_value_is_slugified_and_persisted(self, window,
                                                       monkeypatch):
        monkeypatch.setattr(
            pc_module.QtWidgets.QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("My Studio", True)),
        )
        w, ctl = window(packages={PKG_ID: _pkg_data(namespace="")})

        result = ctl._ensure_namespace(PKG_ID, _pkg_data(namespace=""))

        assert result == "my-studio"
        assert w._install_manager.updates == [
            (PKG_ID, {"namespace": "my-studio"})]

    def test_cancel_returns_none(self, window, monkeypatch):
        monkeypatch.setattr(
            pc_module.QtWidgets.QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("acme", False)),
        )
        _w, ctl = window()

        assert ctl._ensure_namespace(PKG_ID, _pkg_data(namespace="")) is None

    def test_blank_answer_returns_none(self, window, monkeypatch):
        monkeypatch.setattr(
            pc_module.QtWidgets.QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("   ", True)),
        )
        _w, ctl = window()

        assert ctl._ensure_namespace(PKG_ID, _pkg_data(namespace="")) is None

    def test_unslugifiable_answer_returns_none(self, window, monkeypatch):
        monkeypatch.setattr(
            pc_module.QtWidgets.QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("///", True)),
        )
        _w, ctl = window()

        assert ctl._ensure_namespace(PKG_ID, _pkg_data(namespace="")) is None


class TestHomeCatalogueMismatch:
    """Publishing somewhere other than a package's home deserves a prompt.

    Silently forking a package into a second catalogue is how two
    diverging copies of the same pkg_id end up in circulation.
    """

    def _asked(self, monkeypatch, answer):
        calls = []

        def _question(parent, title, text, buttons):
            calls.append(text)
            return answer

        monkeypatch.setattr(pc_module.QtWidgets.QMessageBox, "question",
                            staticmethod(_question))
        return calls

    def test_matching_catalogue_id_passes_silently(self, window, monkeypatch):
        calls = self._asked(monkeypatch, QtWidgets.QMessageBox.No)
        _w, ctl = window()
        data = _pkg_data(home_origin={"type": "embedded",
                                      "catalogue_id": "abc"})

        assert ctl._confirm_home_origin_mismatch(
            data, _catalogue(catalogue_id="abc"))
        assert calls == []

    def test_id_match_wins_over_a_renamed_catalogue(self, window, monkeypatch):
        """The same catalogue can carry different names across machines."""
        calls = self._asked(monkeypatch, QtWidgets.QMessageBox.No)
        _w, ctl = window()
        data = _pkg_data(home_origin={"type": "embedded",
                                      "catalogue_name": "Old Name",
                                      "catalogue_id": "abc"})

        assert ctl._confirm_home_origin_mismatch(
            data, _catalogue(label="New Name", catalogue_id="abc"))
        assert calls == []

    def test_name_match_passes_for_unstamped_catalogues(self, window,
                                                        monkeypatch):
        calls = self._asked(monkeypatch, QtWidgets.QMessageBox.No)
        _w, ctl = window()
        data = _pkg_data(home_origin={"type": "embedded",
                                      "catalogue_name": "Studio"})

        assert ctl._confirm_home_origin_mismatch(data, _catalogue("Studio"))
        assert calls == []

    def test_no_home_origin_passes(self, window, monkeypatch):
        calls = self._asked(monkeypatch, QtWidgets.QMessageBox.No)
        _w, ctl = window()

        assert ctl._confirm_home_origin_mismatch(_pkg_data(), _catalogue())
        assert calls == []

    def test_non_embedded_home_passes(self, window, monkeypatch):
        """A github home has no comparable target at this call site."""
        calls = self._asked(monkeypatch, QtWidgets.QMessageBox.No)
        _w, ctl = window()
        data = _pkg_data(home_origin={"type": "github", "repo": "acme/tools"})

        assert ctl._confirm_home_origin_mismatch(data, _catalogue())
        assert calls == []

    def test_different_catalogue_prompts_and_can_be_declined(self, window,
                                                             monkeypatch):
        calls = self._asked(monkeypatch, QtWidgets.QMessageBox.No)
        _w, ctl = window()
        data = _pkg_data(home_origin={"type": "embedded",
                                      "catalogue_id": "abc"})

        assert not ctl._confirm_home_origin_mismatch(
            data, _catalogue(catalogue_id="xyz"))
        assert len(calls) == 1

    def test_different_catalogue_can_be_confirmed(self, window, monkeypatch):
        self._asked(monkeypatch, QtWidgets.QMessageBox.Yes)
        _w, ctl = window()
        data = _pkg_data(home_origin={"type": "embedded",
                                      "catalogue_id": "abc"})

        assert ctl._confirm_home_origin_mismatch(
            data, _catalogue(catalogue_id="xyz"))


class TestPublishedMap:
    """Drives the "published to" badges, which are also the unpublish menu."""

    def _catalogue_file(self, tmp_path, name, display_name, pkg_ids):
        path = tmp_path / name
        path.write_text(json.dumps({
            "schema_version": "5.0",
            "display_name": display_name,
            "packages": {pid: {} for pid in pkg_ids},
        }), encoding="utf-8")
        return path

    def test_collects_package_ids_per_catalogue(self, window, tmp_path):
        path = self._catalogue_file(tmp_path, "catalogue.json", "Studio",
                                    [PKG_ID, "acme/other"])
        w, ctl = window(catalogues=[_catalogue("Studio", str(path))])

        result = ctl.build_published_map()

        assert result == {PKG_ID: ["Studio"], "acme/other": ["Studio"]}

    def test_uses_the_catalogues_own_display_name(self, window, tmp_path):
        """The badge is what the user clicks to unpublish, so it should
        reflect the author's current naming, not a stale cached label."""
        path = self._catalogue_file(tmp_path, "catalogue.json",
                                    "Renamed Studio", [PKG_ID])
        w, ctl = window(catalogues=[_catalogue("Stale Cache", str(path))])

        assert ctl.build_published_map() == {PKG_ID: ["Renamed Studio"]}

    def test_falls_back_to_the_entry_label(self, window, tmp_path):
        path = self._catalogue_file(tmp_path, "catalogue.json", "", [PKG_ID])
        w, ctl = window(catalogues=[_catalogue("From Entry", str(path))])

        assert ctl.build_published_map() == {PKG_ID: ["From Entry"]}

    def test_remote_catalogues_are_excluded(self, window, tmp_path):
        """You cannot unpublish from one, so the badge would be a dead end."""
        path = self._catalogue_file(tmp_path, "catalogue.json", "Remote",
                                    [PKG_ID])
        w, ctl = window(catalogues=[
            _catalogue("Remote", str(path), is_remote=True)])

        assert ctl.build_published_map() == {}

    def test_missing_file_is_skipped(self, window, tmp_path):
        w, ctl = window(catalogues=[
            _catalogue("Gone", str(tmp_path / "absent.json"))])

        assert ctl.build_published_map() == {}

    def test_damaged_catalogue_is_skipped(self, window, tmp_path):
        path = tmp_path / "catalogue.json"
        path.write_text("{not json", encoding="utf-8")
        w, ctl = window(catalogues=[_catalogue("Broken", str(path))])

        assert ctl.build_published_map() == {}

    def test_a_package_in_two_catalogues_lists_both(self, window, tmp_path):
        a = self._catalogue_file(tmp_path, "a.json", "Alpha", [PKG_ID])
        b = self._catalogue_file(tmp_path, "b.json", "Beta", [PKG_ID])
        w, ctl = window(catalogues=[
            _catalogue("Alpha", str(a)), _catalogue("Beta", str(b))])

        assert ctl.build_published_map() == {PKG_ID: ["Alpha", "Beta"]}

    def test_no_config_returns_empty(self, window):
        w, ctl = window()
        w._config = None

        assert ctl.build_published_map() == {}


class TestStartPublishGuards:
    def test_missing_services_are_a_noop(self, window):
        w, ctl = window()
        w._publisher = None

        ctl.start_publish(PKG_ID)  # must not raise

    def test_unknown_package_is_a_noop(self, window, monkeypatch):
        w, ctl = window()

        def _boom(pkg_data):
            raise AssertionError("should not reach target picking")

        monkeypatch.setattr(ctl, "_pick_target", _boom)

        ctl.start_publish("nope/missing")

    def test_cancelling_the_namespace_prompt_stops_the_publish(
            self, window, monkeypatch):
        w, ctl = window(packages={PKG_ID: _pkg_data(namespace="")})
        monkeypatch.setattr(ctl, "_pick_target",
                            lambda pkg_data: ("embedded", _catalogue()))
        monkeypatch.setattr(ctl, "_ensure_namespace",
                            lambda pkg_id, pkg_data: None)
        ran = []
        monkeypatch.setattr(ctl, "_run_embedded",
                            lambda *a, **k: ran.append(True))

        ctl.start_publish(PKG_ID)

        assert ran == []

    def test_declining_the_mismatch_stops_the_publish(self, window,
                                                      monkeypatch):
        w, ctl = window(packages={PKG_ID: _pkg_data()})
        monkeypatch.setattr(ctl, "_pick_target",
                            lambda pkg_data: ("embedded", _catalogue()))
        monkeypatch.setattr(ctl, "_confirm_home_origin_mismatch",
                            lambda pkg_data, target: False)
        ran = []
        monkeypatch.setattr(ctl, "_run_embedded",
                            lambda *a, **k: ran.append(True))

        ctl.start_publish(PKG_ID)

        assert ran == []

    def test_cancelling_the_confirm_dialog_stops_the_publish(self, window,
                                                             monkeypatch):
        w, ctl = window(packages={PKG_ID: _pkg_data()})
        monkeypatch.setattr(ctl, "_pick_target",
                            lambda pkg_data: ("embedded", _catalogue()))
        monkeypatch.setattr(ctl, "_confirm_home_origin_mismatch",
                            lambda pkg_data, target: True)
        monkeypatch.setattr(ctl, "_confirm_details",
                            lambda pkg_data, label: None)
        ran = []
        monkeypatch.setattr(ctl, "_run_embedded",
                            lambda *a, **k: ran.append(True))

        ctl.start_publish(PKG_ID)

        assert ran == []

    def test_full_embedded_path_reaches_the_runner(self, window, monkeypatch):
        w, ctl = window(packages={PKG_ID: _pkg_data()})
        target = _catalogue()
        monkeypatch.setattr(ctl, "_pick_target",
                            lambda pkg_data: ("embedded", target))
        monkeypatch.setattr(ctl, "_confirm_home_origin_mismatch",
                            lambda pkg_data, t: True)
        monkeypatch.setattr(ctl, "_confirm_details",
                            lambda pkg_data, label: ("notes", True))
        ran = []
        monkeypatch.setattr(ctl, "_run_embedded",
                            lambda *a: ran.append(a))

        ctl.start_publish(PKG_ID)

        assert len(ran) == 1
        pkg_id, _data, got_target, namespace, notes, embed = ran[0]
        assert pkg_id == PKG_ID
        assert got_target is target
        assert namespace == "acme"
        assert notes == "notes"
        assert embed is True

    def test_github_path_reaches_its_own_runner(self, window, monkeypatch):
        w, ctl = window(packages={PKG_ID: _pkg_data()})
        monkeypatch.setattr(ctl, "_pick_target",
                            lambda pkg_data: ("github", "acme/tools"))
        monkeypatch.setattr(ctl, "_confirm_details",
                            lambda pkg_data, label: ("", False))
        ran = []
        monkeypatch.setattr(ctl, "_run_github", lambda *a: ran.append(a))
        monkeypatch.setattr(ctl, "_run_embedded", lambda *a: (_ for _ in ()).throw(
            AssertionError("embedded runner must not fire")))

        ctl.start_publish(PKG_ID)

        assert len(ran) == 1
        assert ran[0][2] == "acme/tools"
