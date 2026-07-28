"""A registration whose source moved should say so, and be fixable.

Registering references the author's files in place rather than copying
them — that is what makes edits take effect without a re-publish. The
cost is that moving, renaming or deleting the source silently strands
the entry: the card stays, and Launch fails with an import error that
never mentions the path.
"""

import os

import pytest

from carton.core.config import Config
from carton.core.env_manager import MayaEnvManager
from carton.core.install_state import has_missing_local_path
from carton.core.installer import InstallManager
from carton.core.path_utils import resolve_local_path
from carton.core.script_manager import ScriptManager


def _entry(local_path, source="local", is_folder=True, **extra):
    entry = {
        "namespace": "acme",
        "name": "rigger",
        "display_name": "Rigger",
        "version": "1.0.0",
        "type": "python_package",
        "source": source,
        "local_path": local_path,
        "is_folder": is_folder,
    }
    entry.update(extra)
    return entry


class TestDetection:
    def test_existing_path_is_not_missing(self, tmp_path):
        src = tmp_path / "rigger"
        src.mkdir()
        assert not has_missing_local_path(_entry(str(src)))

    def test_vanished_path_is_missing(self, tmp_path):
        assert has_missing_local_path(_entry(str(tmp_path / "gone")))

    def test_entry_without_a_local_path_is_not_missing(self):
        """Catalogue installs have no source binding to lose."""
        assert not has_missing_local_path(_entry("", source="registry"))

    def test_catalogue_install_is_not_reported(self, tmp_path):
        """Its bytes are still under packages/ — only the binding is stale."""
        entry = _entry(str(tmp_path / "gone"), source="registry",
                       path="packages/acme/rigger")
        assert not has_missing_local_path(entry)

    def test_non_dict_is_not_missing(self):
        assert not has_missing_local_path(None)
        assert not has_missing_local_path("nope")

    def test_tilde_paths_are_resolved_before_checking(self, monkeypatch,
                                                      tmp_path):
        """Stored paths collapse $HOME to ~; a literal ~ never exists."""
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        real = tmp_path / "tools" / "rigger"
        real.mkdir(parents=True)

        assert not has_missing_local_path(_entry("~/tools/rigger"))


class TestRebindLocalPath:
    def _manager(self, tmp_path):
        install_dir = tmp_path / "carton"
        install_dir.mkdir()
        config = Config(install_dir=str(install_dir))
        env = MayaEnvManager()
        install_mgr = InstallManager(config, env)
        return install_mgr, ScriptManager(config, install_mgr, env), env

    def test_updates_the_stored_path(self, tmp_path):
        install_mgr, script_mgr, _env = self._manager(tmp_path)
        old = tmp_path / "old" / "rigger"
        old.mkdir(parents=True)
        (old / "__init__.py").write_text("", encoding="utf-8")
        new = tmp_path / "new" / "rigger"
        new.mkdir(parents=True)
        (new / "__init__.py").write_text("", encoding="utf-8")
        install_mgr.put_package_entry("acme/rigger", _entry(str(old)))

        assert script_mgr.rebind_local_path("acme/rigger", str(new))

        entry = install_mgr.get_package("acme/rigger")
        # The stored form collapses $HOME to ~ so the entry survives a
        # home-dir rename, so compare through the resolver.
        assert os.path.normpath(
            resolve_local_path(entry["local_path"])
        ) == os.path.normpath(str(new))
        assert not has_missing_local_path(entry)

    def test_identity_is_untouched(self, tmp_path):
        """Same tool, new place — not a new registration."""
        install_mgr, script_mgr, _env = self._manager(tmp_path)
        new = tmp_path / "new" / "rigger"
        new.mkdir(parents=True)
        install_mgr.put_package_entry("acme/rigger",
                                      _entry(str(tmp_path / "gone")))

        script_mgr.rebind_local_path("acme/rigger", str(new))

        entry = install_mgr.get_package("acme/rigger")
        assert "acme/rigger" in install_mgr.get_installed_packages()
        assert entry["namespace"] == "acme"
        assert entry["name"] == "rigger"

    def test_old_path_comes_off_sys_path(self, tmp_path, monkeypatch):
        """Otherwise an import still resolves against the abandoned copy."""
        import sys

        install_mgr, script_mgr, _env = self._manager(tmp_path)
        old = tmp_path / "old" / "rigger"
        old.mkdir(parents=True)
        (old / "__init__.py").write_text("", encoding="utf-8")
        new = tmp_path / "new" / "rigger"
        new.mkdir(parents=True)
        (new / "__init__.py").write_text("", encoding="utf-8")

        install_mgr.put_package_entry("acme/rigger", _entry(str(old)))
        script_mgr.activate("acme/rigger")
        assert str(old.parent) in sys.path

        try:
            script_mgr.rebind_local_path("acme/rigger", str(new))
            assert str(old.parent) not in sys.path
            assert str(new.parent) in sys.path
        finally:
            for p in (str(old.parent), str(old), str(new.parent), str(new)):
                while p in sys.path:
                    sys.path.remove(p)

    def test_unknown_package_is_a_noop(self, tmp_path):
        install_mgr, script_mgr, _env = self._manager(tmp_path)
        assert script_mgr.rebind_local_path("nope/missing", str(tmp_path)) is False


pytest.importorskip("pytestqt")

from carton.ui.package_card import PackageCard  # noqa: E402
from carton.ui.i18n import t  # noqa: E402


class TestCardSurfacesTheProblem:
    def test_missing_source_offers_relink_not_launch(self, qtbot, tmp_path):
        data = _entry(str(tmp_path / "gone"))
        data["_local_script"] = True
        card = PackageCard("acme/rigger", data, installed_version="1.0.0")
        qtbot.addWidget(card)

        from carton.ui.compat import QtWidgets
        labels = [b.text() for b in card.findChildren(QtWidgets.QPushButton)]
        assert t("relink") in labels
        assert t("launch") not in labels

    def test_present_source_offers_launch(self, qtbot, tmp_path):
        src = tmp_path / "rigger"
        src.mkdir()
        data = _entry(str(src))
        data["_local_script"] = True
        card = PackageCard("acme/rigger", data, installed_version="1.0.0")
        qtbot.addWidget(card)

        from carton.ui.compat import QtWidgets
        labels = [b.text() for b in card.findChildren(QtWidgets.QPushButton)]
        assert t("launch") in labels
        assert t("relink") not in labels

    def test_relink_button_emits_the_signal(self, qtbot, tmp_path):
        from carton.ui.compat import QtWidgets

        data = _entry(str(tmp_path / "gone"))
        data["_local_script"] = True
        card = PackageCard("acme/rigger", data, installed_version="1.0.0")
        qtbot.addWidget(card)
        button = next(b for b in card.findChildren(QtWidgets.QPushButton)
                      if b.text() == t("relink"))

        with qtbot.waitSignal(card.relink_requested) as blocker:
            button.click()

        assert blocker.args == ["acme/rigger"]

    def test_missing_badge_is_shown(self, qtbot, tmp_path):
        from carton.ui.compat import QtWidgets

        data = _entry(str(tmp_path / "gone"))
        data["_local_script"] = True
        card = PackageCard("acme/rigger", data, installed_version="1.0.0")
        qtbot.addWidget(card)

        texts = [lbl.text() for lbl in card.findChildren(QtWidgets.QLabel)]
        assert any(t("source_missing_badge") in txt for txt in texts)
