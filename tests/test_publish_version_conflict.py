"""Publishing over an existing version should offer a way forward.

The old behaviour named the version that was taken and stopped. The
author then had to close the dialog, find the card, open Edit, work out
a version that wasn't already published, type it, save, and start the
publish over — for the single most common publish outcome there is.
"""

import types

import pytest

from carton.core.publisher import VersionConflictError
from carton.models.version import next_free_patch


class TestNextFreePatch:
    def test_increments_the_patch(self):
        assert next_free_patch("1.2.3", []) == "1.2.4"

    def test_walks_past_versions_already_taken(self):
        """Otherwise a second collision sends the author round again."""
        assert next_free_patch("1.0.0", ["1.0.1", "1.0.2"]) == "1.0.3"

    def test_ignores_unrelated_taken_versions(self):
        assert next_free_patch("1.0.0", ["2.0.0", "1.1.0"]) == "1.0.1"

    def test_accepts_a_mapping_of_versions(self):
        """The catalogue stores versions as dict keys, not a list."""
        assert next_free_patch("0.9.9", {"0.9.10": {}}) == "0.9.11"

    def test_non_semver_has_no_successor(self):
        """Guessing one would publish under a number nobody chose."""
        assert next_free_patch("2024-spring", []) is None
        assert next_free_patch("", []) is None
        assert next_free_patch(None, []) is None

    def test_two_digit_components_are_numeric_not_lexical(self):
        assert next_free_patch("1.0.9", []) == "1.0.10"


class TestVersionConflictError:
    def test_carries_the_published_versions(self):
        exc = VersionConflictError("1.0.0", published_versions=["1.0.0", "1.0.1"])
        assert exc.version == "1.0.0"
        assert exc.published_versions == ["1.0.0", "1.0.1"]

    def test_defaults_to_no_known_versions(self):
        assert VersionConflictError("1.0.0").published_versions == []


pytest.importorskip("pytestqt")

from carton.ui.compat import QtWidgets  # noqa: E402
import carton.ui._publish_controller as pc_module  # noqa: E402
from carton.ui._publish_controller import PublishController  # noqa: E402


PKG_ID = "acme/rigger"


class _StubInstallManager:
    def __init__(self, present=True):
        self.updates = []
        self._present = present

    def update_package_fields(self, pkg_id, fields):
        if not self._present:
            return False
        self.updates.append((pkg_id, dict(fields)))
        return True

    def get_installed_packages(self):
        return {}

    def rekey_package(self, old_id, new_id, fields=None):
        return True


class _StubPublisher:
    """Raises a conflict on the first call, succeeds on the next."""

    def __init__(self, taken):
        self.calls = []
        self._taken = list(taken)

    def publish(self, pkg_data, target, namespace="", release_notes="",
                embed_source_path=False):
        version = pkg_data.get("version")
        self.calls.append(version)
        if version in self._taken:
            raise VersionConflictError(version, published_versions=self._taken)
        return {
            "id": PKG_ID, "namespace": "acme", "name": "rigger",
            "version": version, "warnings": [],
        }


class _StubWindow(QtWidgets.QWidget):
    def __init__(self, taken):
        super().__init__()
        self._publisher = _StubPublisher(taken)
        self._install_manager = _StubInstallManager()
        self._config = types.SimpleNamespace(catalogues=[])
        self._card_layout = QtWidgets.QVBoxLayout()
        self.refreshes = 0

    def refresh(self):
        self.refreshes += 1


def _target():
    return types.SimpleNamespace(
        label="Studio", path="/tmp/studio/catalogue.json", is_remote=False,
        to_home_origin_meta=lambda: {"type": "embedded"},
    )


class _FakeMessageBox:
    """Stands in for QMessageBox so the conflict dialog can be driven.

    Records everything put in front of the user and reports whichever
    button ``state["accept"]`` selects. Class attributes mirror the enum
    members the controller reads off the class.
    """

    Question = QtWidgets.QMessageBox.Question
    Warning = QtWidgets.QMessageBox.Warning
    Information = QtWidgets.QMessageBox.Information
    AcceptRole = QtWidgets.QMessageBox.AcceptRole
    RejectRole = QtWidgets.QMessageBox.RejectRole

    state = None  # bound per-test by the `answer` fixture

    def __init__(self, parent=None):
        self._accept_btn = object()
        self._reject_btn = object()

    def setIcon(self, _icon):
        pass

    def setWindowTitle(self, _title):
        pass

    def setText(self, text):
        self.state["shown"].append(text)

    def setInformativeText(self, text):
        self.state["shown"].append(text)

    def addButton(self, label, role):
        self.state["shown"].append(label)
        if role == self.AcceptRole:
            return self._accept_btn
        return self._reject_btn

    def exec_(self):
        return 0

    def clickedButton(self):
        return self._accept_btn if self.state["accept"] else self._reject_btn

    @classmethod
    def warning(cls, *args, **kwargs):
        cls.state["shown"].append(args)

    @classmethod
    def information(cls, *args, **kwargs):
        cls.state["shown"].append(args)


class _QtShim:
    """Proxies QtWidgets with QMessageBox swapped out.

    Assigning to ``QtWidgets.QMessageBox`` directly would mutate the
    real PySide module for every test that runs afterwards, so the swap
    happens on the controller module's own reference instead.
    """

    def __init__(self, real, message_box):
        self._real = real
        self.QMessageBox = message_box

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def answer(monkeypatch):
    """Drive the conflict dialog without opening one.

    ``state["accept"]`` picks the button; ``state["shown"]`` collects
    every string the dialog would have displayed.
    """
    state = {"accept": True, "shown": []}
    box = type("_BoundFakeMessageBox", (_FakeMessageBox,), {"state": state})
    monkeypatch.setattr(pc_module, "QtWidgets", _QtShim(QtWidgets, box))
    return state


@pytest.fixture
def controller(qtbot, monkeypatch):
    def _make(taken):
        w = _StubWindow(taken)
        qtbot.addWidget(w)
        ctl = PublishController(w)
        # The busy-state helper walks real cards; nothing to update here.
        monkeypatch.setattr(ctl, "set_publish_button_state",
                            lambda pkg_id, busy=True: None)
        monkeypatch.setattr(ctl, "_find_catalogue_by_name", lambda name: None)
        return w, ctl
    return _make


def _pkg_data(version="1.0.0"):
    return {"name": "rigger", "namespace": "acme", "version": version,
            "display_name": "Rigger", "type": "python_package"}


class TestConflictOffersABump:
    def test_accepting_records_and_republishes(self, controller, answer):
        answer["accept"] = True
        w, ctl = controller(["1.0.0"])

        ctl._run_embedded(PKG_ID, _pkg_data("1.0.0"), _target(),
                          "acme", "", False)

        # First attempt collided, second went out under the bumped version.
        assert w._publisher.calls == ["1.0.0", "1.0.1"]
        assert w._install_manager.updates == [(PKG_ID, {"version": "1.0.1"})]
        assert w.refreshes == 1

    def test_declining_changes_nothing(self, controller, answer):
        answer["accept"] = False
        w, ctl = controller(["1.0.0"])

        ctl._run_embedded(PKG_ID, _pkg_data("1.0.0"), _target(),
                          "acme", "", False)

        assert w._publisher.calls == ["1.0.0"]
        assert w._install_manager.updates == []
        assert w.refreshes == 0

    def test_proposal_skips_versions_already_out(self, controller, answer):
        answer["accept"] = True
        w, ctl = controller(["1.0.0", "1.0.1", "1.0.2"])

        ctl._run_embedded(PKG_ID, _pkg_data("1.0.0"), _target(),
                          "acme", "", False)

        assert w._publisher.calls == ["1.0.0", "1.0.3"]

    def test_proposed_version_is_offered_in_the_dialog(self, controller,
                                                       answer):
        answer["accept"] = False
        w, ctl = controller(["1.0.0"])

        ctl._run_embedded(PKG_ID, _pkg_data("1.0.0"), _target(),
                          "acme", "", False)

        assert any("1.0.1" in str(s) for s in answer["shown"])

    def test_non_semver_version_falls_back_to_a_warning(self, controller,
                                                        answer):
        answer["accept"] = True
        w, ctl = controller(["nightly"])

        ctl._run_embedded(PKG_ID, _pkg_data("nightly"), _target(),
                          "acme", "", False)

        # No bump proposed, no republish attempted.
        assert w._publisher.calls == ["nightly"]
        assert w._install_manager.updates == []

    def test_unrecorded_bump_does_not_republish(self, controller, answer,
                                                monkeypatch):
        """Republishing a version we failed to persist re-runs the collision."""
        answer["accept"] = True
        w, ctl = controller(["1.0.0"])
        w._install_manager = _StubInstallManager(present=False)
        monkeypatch.setattr(pc_module, "show_error",
                            lambda parent, exc, operation=None: None)

        ctl._run_embedded(PKG_ID, _pkg_data("1.0.0"), _target(),
                          "acme", "", False)

        assert w._publisher.calls == ["1.0.0"]
