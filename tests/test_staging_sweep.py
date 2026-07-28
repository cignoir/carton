"""Staging must not grow without bound.

Every zip that passes through staging has a consumer that deletes it —
on the paths that succeed. Failed installs, abandoned GitHub publishes
and superseded self-updates leave theirs behind, and nothing used to
collect them.
"""

import json
import os
import time

from carton.core.staging import (
    DEFAULT_MAX_AGE_SECONDS,
    sweep_staging,
    sweep_all,
)


def _aged_file(path, age_seconds):
    path.write_bytes(b"zip")
    stamp = time.time() - age_seconds
    os.utime(str(path), (stamp, stamp))
    return path


class TestSweepStaging:
    def test_removes_files_past_the_cutoff(self, tmp_path):
        old = _aged_file(tmp_path / "old-1.0.0.zip", DEFAULT_MAX_AGE_SECONDS + 60)

        assert sweep_staging(str(tmp_path)) == 1
        assert not old.exists()

    def test_keeps_recent_files(self, tmp_path):
        fresh = _aged_file(tmp_path / "fresh-1.0.0.zip", 60)

        assert sweep_staging(str(tmp_path)) == 0
        assert fresh.exists()

    def test_spares_explicitly_kept_paths(self, tmp_path):
        pinned = _aged_file(tmp_path / "pinned.zip", DEFAULT_MAX_AGE_SECONDS * 5)

        removed = sweep_staging(str(tmp_path), keep=[str(pinned)])

        assert removed == 0
        assert pinned.exists()

    def test_leaves_subdirectories_alone(self, tmp_path):
        nested = tmp_path / "nested"
        nested.mkdir()
        stamp = time.time() - DEFAULT_MAX_AGE_SECONDS * 2
        os.utime(str(nested), (stamp, stamp))

        sweep_staging(str(tmp_path))

        assert nested.is_dir()

    def test_missing_directory_is_a_noop(self, tmp_path):
        assert sweep_staging(str(tmp_path / "absent")) == 0

    def test_empty_path_is_a_noop(self):
        assert sweep_staging("") == 0


class TestSweepAll:
    def test_sweeps_install_dir_and_bootstrap_staging(
            self, tmp_path, monkeypatch):
        import carton.core.staging as staging_module

        install_staging = tmp_path / "data" / ".staging"
        install_staging.mkdir(parents=True)
        boot_dir = tmp_path / "boot"
        boot_staging = boot_dir / ".staging"
        boot_staging.mkdir(parents=True)

        _aged_file(install_staging / "failed-1.0.0.zip",
                   DEFAULT_MAX_AGE_SECONDS * 2)
        _aged_file(boot_staging / "carton-0.0.1.zip",
                   DEFAULT_MAX_AGE_SECONDS * 2)

        monkeypatch.setattr(
            "carton.core.config.default_bootstrap_dir", lambda: str(boot_dir))

        class _Config:
            staging_dir = str(install_staging)

        assert staging_module.sweep_all(_Config()) == 2
        assert list(install_staging.iterdir()) == []
        assert list(boot_staging.iterdir()) == []

    def test_a_recorded_pending_update_is_never_swept(
            self, tmp_path, monkeypatch):
        """The staged zip a restart is going to apply must survive.

        Its name encodes the version, so an update staged before a long
        break is older than the cutoff by the time Maya next starts.
        """
        import carton.core.staging as staging_module

        boot_dir = tmp_path / "boot"
        boot_staging = boot_dir / ".staging"
        boot_staging.mkdir(parents=True)
        staged = _aged_file(boot_staging / "carton-9.9.9.zip",
                            DEFAULT_MAX_AGE_SECONDS * 3)
        (boot_dir / "pending_update.json").write_text(json.dumps({
            "version": "9.9.9",
            "staged_zip": os.path.join(".staging", "carton-9.9.9.zip"),
        }), encoding="utf-8")

        monkeypatch.setattr(
            "carton.core.config.default_bootstrap_dir", lambda: str(boot_dir))

        install_staging = tmp_path / "data" / ".staging"
        install_staging.mkdir(parents=True)

        class _Config:
            staging_dir = str(install_staging)

        assert staging_module.sweep_all(_Config()) == 0
        assert staged.exists()

    def test_damaged_pending_record_does_not_break_the_sweep(
            self, tmp_path, monkeypatch):
        import carton.core.staging as staging_module

        boot_dir = tmp_path / "boot"
        boot_staging = boot_dir / ".staging"
        boot_staging.mkdir(parents=True)
        _aged_file(boot_staging / "orphan.zip", DEFAULT_MAX_AGE_SECONDS * 2)
        (boot_dir / "pending_update.json").write_text("{trunc",
                                                      encoding="utf-8")

        monkeypatch.setattr(
            "carton.core.config.default_bootstrap_dir", lambda: str(boot_dir))

        install_staging = tmp_path / "data" / ".staging"
        install_staging.mkdir(parents=True)

        class _Config:
            staging_dir = str(install_staging)

        assert staging_module.sweep_all(_Config()) == 1
