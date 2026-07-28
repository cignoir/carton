"""Tests for crash-safe JSON persistence.

Two properties are load-bearing here and neither is visible in normal
operation, which is exactly why they need tests: writes must be atomic
(so a crash can't truncate a state file), and reads of startup-critical
files must degrade instead of raising (so a truncated file costs the
user that file's contents, not the ability to launch Carton).
"""

import json
import os

import pytest

from carton.core.config import Config
from carton.core.installer import InstallManager
from carton.core.json_io import read_json_quarantining, write_json_atomic


class TestWriteJsonAtomic:
    def test_creates_parent_directories(self, tmp_path):
        target = tmp_path / "a" / "b" / "state.json"
        write_json_atomic(str(target), {"k": "v"})
        assert json.loads(target.read_text(encoding="utf-8")) == {"k": "v"}

    def test_leaves_no_temp_file_behind(self, tmp_path):
        target = tmp_path / "state.json"
        write_json_atomic(str(target), {"k": "v"})
        assert not (tmp_path / "state.json.tmp").exists()

    def test_previous_content_survives_a_failed_write(self, tmp_path):
        """The original must still be readable if serialisation blows up."""
        target = tmp_path / "state.json"
        write_json_atomic(str(target), {"good": True})

        class Unserialisable:
            pass

        with pytest.raises(TypeError):
            write_json_atomic(str(target), {"bad": Unserialisable()})

        assert json.loads(target.read_text(encoding="utf-8")) == {"good": True}

    def test_trailing_newline_is_opt_in(self, tmp_path):
        plain = tmp_path / "plain.json"
        newline = tmp_path / "newline.json"
        write_json_atomic(str(plain), {"k": 1})
        write_json_atomic(str(newline), {"k": 1}, trailing_newline=True)

        assert not plain.read_text(encoding="utf-8").endswith("\n")
        assert newline.read_text(encoding="utf-8").endswith("\n")

    def test_non_ascii_is_written_verbatim(self, tmp_path):
        target = tmp_path / "state.json"
        write_json_atomic(str(target), {"name": "マイツール"})
        assert "マイツール" in target.read_text(encoding="utf-8")


class TestReadJsonQuarantining:
    def test_missing_file_returns_default_without_quarantine(self, tmp_path):
        data, quarantined = read_json_quarantining(
            str(tmp_path / "nope.json"), {"fallback": True})
        assert data == {"fallback": True}
        assert quarantined == ""

    def test_valid_file_reads_through(self, tmp_path):
        target = tmp_path / "state.json"
        target.write_text('{"k": "v"}', encoding="utf-8")
        data, quarantined = read_json_quarantining(str(target), {})
        assert data == {"k": "v"}
        assert quarantined == ""

    def test_truncated_file_is_moved_aside(self, tmp_path):
        target = tmp_path / "state.json"
        target.write_text('{"k": "v', encoding="utf-8")

        data, quarantined = read_json_quarantining(str(target), {"d": 1})

        assert data == {"d": 1}
        assert quarantined
        assert not target.exists()
        # The damaged bytes are preserved, never deleted.
        assert os.path.exists(quarantined)
        assert open(quarantined, encoding="utf-8").read() == '{"k": "v'

    def test_wrong_shape_counts_as_corruption(self, tmp_path):
        target = tmp_path / "state.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")

        data, quarantined = read_json_quarantining(str(target), {"d": 1})

        assert data == {"d": 1}
        assert quarantined

    def test_wrong_shape_allowed_when_not_required(self, tmp_path):
        target = tmp_path / "state.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")

        data, quarantined = read_json_quarantining(
            str(target), None, require_mapping=False)

        assert data == [1, 2, 3]
        assert quarantined == ""


class TestConfigSurvivesCorruption:
    """A damaged config.json must not stop Carton from launching."""

    def test_load_recovers_instead_of_raising(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"catalogues": [{"path": "x"}], "install_di',
                        encoding="utf-8")

        cfg = Config.load(str(path))

        assert cfg.catalogues == []
        assert cfg.recovered_from
        assert os.path.exists(cfg.recovered_from)

    def test_normal_load_reports_no_recovery(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({
            "catalogues": [{"path": "https://example.com/catalogue.json"}],
            "install_dir": str(tmp_path / "data"),
        }), encoding="utf-8")

        cfg = Config.load(str(path))

        assert cfg.recovered_from == ""
        assert len(cfg.catalogues) == 1

    def test_save_is_atomic(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = Config(install_dir=str(tmp_path / "data"))
        cfg.add_catalogue("https://example.com/catalogue.json")
        cfg.save(str(path))

        assert not (tmp_path / "config.json.tmp").exists()
        assert Config.load(str(path)).catalogues[0].path == \
            "https://example.com/catalogue.json"

    def test_missing_config_is_not_a_recovery(self, tmp_path):
        cfg = Config.load(str(tmp_path / "absent.json"))
        assert cfg.recovered_from == ""
        assert cfg.catalogues == []


class TestInstalledJsonSurvivesCorruption:
    """Same rule for installed.json, with a stronger safety net.

    The installed packages are still on disk under ``packages/`` even
    when the index is lost, so degrading here is recoverable; raising
    during ``carton.startup()`` is not.
    """

    class _Env:
        def snapshot(self):
            return {}

        def diff_since(self, _before):
            return {}

    def test_corrupt_index_starts_empty_and_quarantines(self, tmp_path):
        install_dir = tmp_path / "carton"
        install_dir.mkdir()
        (install_dir / "installed.json").write_text(
            '{"packages": {"a/b": ', encoding="utf-8")
        config = Config(install_dir=str(install_dir))

        mgr = InstallManager(config, self._Env())

        assert mgr.get_installed_packages() == {}
        quarantined = list(install_dir.glob("installed.json.corrupt-*"))
        assert len(quarantined) == 1

    def test_save_writes_atomically(self, tmp_path):
        install_dir = tmp_path / "carton"
        install_dir.mkdir()
        config = Config(install_dir=str(install_dir))
        mgr = InstallManager(config, self._Env())

        mgr._installed["packages"]["ns/tool"] = {"version": "1.0.0"}
        mgr._save_installed()

        assert not (install_dir / "installed.json.tmp").exists()
        reloaded = json.loads(
            (install_dir / "installed.json").read_text(encoding="utf-8"))
        assert reloaded["packages"]["ns/tool"]["version"] == "1.0.0"
