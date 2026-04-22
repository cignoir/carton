"""Tests for :mod:`carton.core.gh_cli`.

We never hit the real ``gh`` binary — all subprocess calls are patched.
The goal is to lock in:

* command-line shape (``gh release create <tag> --repo <repo> --notes ...``)
* error mapping (missing binary, non-zero exit, timeout → GhCliError)
* manual-instruction fallback's copy-pasteability
"""

import subprocess

import pytest

from carton.core import gh_cli


class _FakeResult(object):
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestIsAvailable:
    def test_returns_false_when_not_on_path(self, monkeypatch):
        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: None)
        assert gh_cli.is_available() is False

    def test_returns_true_when_authenticated(self, monkeypatch):
        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(
            gh_cli.subprocess, "run",
            lambda *a, **kw: _FakeResult(returncode=0, stdout="Logged in"),
        )
        assert gh_cli.is_available() is True

    def test_returns_false_when_auth_status_nonzero(self, monkeypatch):
        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(
            gh_cli.subprocess, "run",
            lambda *a, **kw: _FakeResult(returncode=1, stderr="not logged in"),
        )
        assert gh_cli.is_available() is False

    def test_returns_false_on_os_error(self, monkeypatch):
        """Unlikely-but-real: ``which`` lies about PATH. Don't crash."""
        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: "/usr/bin/gh")

        def _boom(*a, **kw):
            raise OSError("exec format error")

        monkeypatch.setattr(gh_cli.subprocess, "run", _boom)
        assert gh_cli.is_available() is False


class TestCreateRelease:
    def test_missing_binary_raises(self, monkeypatch):
        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: None)
        with pytest.raises(gh_cli.GhCliError, match="not found"):
            gh_cli.create_release("owner/repo", "v1.0.0")

    def test_builds_expected_command(self, monkeypatch, tmp_path):
        """Verify every caller-relevant flag appears in the command line."""
        zip_asset = tmp_path / "tool-1.0.0.zip"
        zip_asset.write_bytes(b"zip")
        sums_asset = tmp_path / "SHA256SUMS"
        sums_asset.write_text("abc  tool-1.0.0.zip\n", encoding="utf-8")

        captured = {}

        def _fake_run(cmd, **kw):
            captured["cmd"] = list(cmd)
            captured["kw"] = kw
            return _FakeResult(returncode=0, stdout="https://github.com/o/r/releases/tag/v1.0.0")

        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(gh_cli.subprocess, "run", _fake_run)

        url = gh_cli.create_release(
            "owner/repo", "v1.0.0",
            title="Tool 1.0.0", notes="first release",
            assets=[str(zip_asset), str(sums_asset)],
            prerelease=False, draft=False,
        )

        assert url == "https://github.com/o/r/releases/tag/v1.0.0"
        cmd = captured["cmd"]
        assert cmd[:5] == ["gh", "release", "create", "v1.0.0", "--repo"]
        assert cmd[5] == "owner/repo"
        # Flag order beyond --repo isn't contractually fixed, so check
        # by membership rather than position.
        assert "--title" in cmd and "Tool 1.0.0" in cmd
        assert "--notes" in cmd and "first release" in cmd
        assert str(zip_asset) in cmd
        assert str(sums_asset) in cmd
        assert "--draft" not in cmd
        assert "--prerelease" not in cmd

    def test_empty_notes_are_still_passed(self, monkeypatch):
        """Without --notes, gh opens an editor; we must never let that happen."""
        captured = {}

        def _fake_run(cmd, **kw):
            captured["cmd"] = list(cmd)
            return _FakeResult(returncode=0, stdout="url")

        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(gh_cli.subprocess, "run", _fake_run)

        gh_cli.create_release("o/r", "v0.1.0")
        cmd = captured["cmd"]
        assert "--notes" in cmd
        # The value after --notes should be the empty string — never
        # elided (gh treats elision as "open EDITOR").
        notes_idx = cmd.index("--notes")
        assert cmd[notes_idx + 1] == ""

    def test_missing_asset_raises_before_invocation(self, monkeypatch):
        """Fail loud on the caller side rather than letting gh error later."""
        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: "/usr/bin/gh")

        called = []
        monkeypatch.setattr(
            gh_cli.subprocess, "run",
            lambda *a, **kw: called.append(True) or _FakeResult(),
        )
        with pytest.raises(gh_cli.GhCliError, match="asset not found"):
            gh_cli.create_release("o/r", "v1", assets=["/does/not/exist.zip"])
        assert called == []

    def test_nonzero_exit_carries_stderr(self, monkeypatch):
        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(
            gh_cli.subprocess, "run",
            lambda *a, **kw: _FakeResult(returncode=1, stderr="repo not found\n"),
        )
        with pytest.raises(gh_cli.GhCliError) as exc:
            gh_cli.create_release("ghost/repo", "v1")
        assert "exit 1" in str(exc.value)
        assert exc.value.stderr == "repo not found"

    def test_timeout_maps_to_gh_cli_error(self, monkeypatch):
        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: "/usr/bin/gh")

        def _boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="gh", timeout=10)

        monkeypatch.setattr(gh_cli.subprocess, "run", _boom)
        with pytest.raises(gh_cli.GhCliError, match="invocation failed"):
            gh_cli.create_release("o/r", "v1")

    def test_draft_prerelease_flags(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(gh_cli.shutil, "which", lambda _: "/usr/bin/gh")

        def _fake_run(cmd, **kw):
            captured["cmd"] = list(cmd)
            return _FakeResult(returncode=0, stdout="")

        monkeypatch.setattr(gh_cli.subprocess, "run", _fake_run)
        gh_cli.create_release("o/r", "v1", draft=True, prerelease=True)
        assert "--draft" in captured["cmd"]
        assert "--prerelease" in captured["cmd"]


class TestManualInstructions:
    def test_includes_tag_repo_and_assets(self, tmp_path):
        asset = tmp_path / "tool-1.0.0.zip"
        asset.write_bytes(b"")
        out = gh_cli.build_manual_instructions(
            "owner/repo", "v1.0.0", [str(asset)], notes="first release",
        )
        assert "owner/repo" in out
        assert "v1.0.0" in out
        assert str(asset) in out
        # Notes should be quoted so shell-copy-paste actually works with
        # spaces and punctuation.
        assert "'first release'" in out

    def test_works_with_no_notes_or_assets(self):
        out = gh_cli.build_manual_instructions("o/r", "v0.1.0", [])
        assert "o/r" in out and "v0.1.0" in out
