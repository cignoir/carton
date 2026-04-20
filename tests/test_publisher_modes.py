"""Tests for :meth:`Publisher.publish_github` — the v5.0 github-origin mode.

Covers the behaviour described in Step 3 of the v5.0 plan:

* Builds a zip + SHA256SUMS sidecar locally (same zip shape as the
  embedded path so consumers see identical package.json bytes).
* Calls ``gh release create`` with the right repo/tag/assets when
  ``gh`` is available.
* Falls back to copy-pasteable manual steps when ``gh`` isn't usable
  or when the caller explicitly disables it.
* Surfaces ``gh release create`` failures as a warning + manual fallback
  instead of blowing up mid-publish.
* Still writes namespace/name back into the source tree so the next
  publish from this clone converges.

All ``gh`` interactions go through an injected stub module so no real
binary is ever invoked.
"""

import json
import os
import zipfile

import pytest

from carton.core.config import Config
from carton.core.publisher import MissingNamespaceError, Publisher


class _StubGh(object):
    """Drop-in replacement for :mod:`carton.core.gh_cli` in tests."""

    # Mirror the real module's exception so ``except gh.GhCliError`` in
    # the publisher sees a matching type via the injected module.
    class GhCliError(RuntimeError):
        def __init__(self, message, stderr=""):
            super().__init__(message)
            self.stderr = stderr

    def __init__(self, available=True, raises=None, release_url="https://x"):
        self._available = available
        self._raises = raises
        self._release_url = release_url
        self.calls = []

    def is_available(self):
        return self._available

    def create_release(self, repo, tag, title="", notes="",
                       assets=None, draft=False, prerelease=False, cwd=None):
        self.calls.append({
            "repo": repo, "tag": tag, "title": title, "notes": notes,
            "assets": list(assets or []), "draft": draft,
            "prerelease": prerelease, "cwd": cwd,
        })
        if self._raises is not None:
            raise self._raises
        return self._release_url

    def build_manual_instructions(self, repo, tag, assets, notes=""):
        return "MANUAL:{}:{}:{}".format(repo, tag, ",".join(assets))


def _make_tool(tmp_path, version="1.0.0"):
    """Minimal python_package layout the publisher accepts."""
    proj = tmp_path / "my_tool_proj"
    module = proj / "my_tool"
    module.mkdir(parents=True)
    (module / "__init__.py").write_text("def show(): pass\n", encoding="utf-8")
    (proj / "package.json").write_text(json.dumps({
        "namespace": "mystudio",
        "name": "my_tool",
        "version": version,
        "type": "python_package",
    }), encoding="utf-8")
    return str(proj)


def _pkg_data(local_path, version="1.0.0"):
    return {
        "namespace": "mystudio",
        "name": "my_tool",
        "display_name": "My Tool",
        "version": version,
        "type": "python_package",
        "local_path": local_path,
        "is_folder": True,
        "entry_point": {"type": "python", "module": "my_tool", "function": "show"},
        "author": "tester",
        "description": "t",
        "tags": [],
        "maya_versions": ["2024", "2025"],
    }


@pytest.fixture
def publisher(tmp_path):
    cfg = Config(install_dir=str(tmp_path / "install"))
    # staging_dir lives under install_dir; make sure it exists for zip writes.
    os.makedirs(cfg.staging_dir, exist_ok=True)
    return Publisher(cfg)


class TestGhAvailablePath:
    def test_builds_zip_and_sums_then_calls_gh(self, publisher, tmp_path):
        local = _make_tool(tmp_path)
        gh = _StubGh(available=True, release_url="https://github.com/mystudio/my_tool/releases/tag/v1.0.0")

        result = publisher.publish_github(
            _pkg_data(local),
            repo="mystudio/my_tool",
            release_notes="first release",
            gh_cli_module=gh,
        )

        assert result["id"] == "mystudio/my_tool"
        assert result["tag"] == "v1.0.0"
        assert result["repo"] == "mystudio/my_tool"
        assert result["release_url"].endswith("/v1.0.0")
        # Zip must exist and contain the expected files.
        assert os.path.exists(result["zip_path"])
        with zipfile.ZipFile(result["zip_path"]) as zf:
            names = set(zf.namelist())
        assert "package.json" in names
        assert any(n.endswith("__init__.py") for n in names)
        # SHA256SUMS sits next to the zip and records the zip's hash
        # in the permissive shape GithubOrigin parses (sha, two spaces,
        # filename — no leading ``*``).
        with open(result["sha256sums_path"], "r", encoding="utf-8") as f:
            sums = f.read()
        assert result["sha256"] in sums
        assert os.path.basename(result["zip_path"]) in sums
        # gh was called with both assets and the v5.0-shaped tag.
        assert len(gh.calls) == 1
        call = gh.calls[0]
        assert call["repo"] == "mystudio/my_tool"
        assert call["tag"] == "v1.0.0"
        assert result["zip_path"] in call["assets"]
        assert result["sha256sums_path"] in call["assets"]
        # No warnings on a clean run.
        assert "warnings" not in result

    def test_custom_tag_prefix(self, publisher, tmp_path):
        local = _make_tool(tmp_path)
        gh = _StubGh(available=True)
        result = publisher.publish_github(
            _pkg_data(local),
            repo="mystudio/my_tool",
            tag_prefix="",  # bare version, no leading 'v'
            gh_cli_module=gh,
        )
        assert result["tag"] == "1.0.0"
        assert gh.calls[0]["tag"] == "1.0.0"

    def test_title_falls_back_to_name(self, publisher, tmp_path):
        """Display name comes from pkg_data but the bare name is the
        safe fallback if someone publishes without one set."""
        local = _make_tool(tmp_path)
        data = _pkg_data(local)
        data["display_name"] = ""
        gh = _StubGh(available=True)
        publisher.publish_github(data, repo="mystudio/my_tool", gh_cli_module=gh)
        assert "my_tool 1.0.0" in gh.calls[0]["title"]


class TestGhUnavailablePath:
    def test_returns_manual_steps_without_invoking_gh(self, publisher, tmp_path):
        local = _make_tool(tmp_path)
        gh = _StubGh(available=False)
        result = publisher.publish_github(
            _pkg_data(local), repo="mystudio/my_tool",
            release_notes="hi", gh_cli_module=gh,
        )
        assert "manual_steps" in result
        assert "release_url" not in result
        # Artifacts are built regardless so the user can upload manually.
        assert os.path.exists(result["zip_path"])
        assert os.path.exists(result["sha256sums_path"])
        # Warning surfaces so the UI can prompt for ``gh auth login``.
        assert result.get("warnings") == [
            "gh CLI unavailable; fell back to manual steps"
        ]
        # gh.create_release must NOT have been called.
        assert gh.calls == []

    def test_use_gh_cli_false_is_silent_manual(self, publisher, tmp_path):
        """Explicit dry-run: caller didn't want gh, so no warning is emitted."""
        local = _make_tool(tmp_path)
        gh = _StubGh(available=True)
        result = publisher.publish_github(
            _pkg_data(local), repo="mystudio/my_tool",
            use_gh_cli=False, gh_cli_module=gh,
        )
        assert "manual_steps" in result
        assert "warnings" not in result
        assert gh.calls == []


class TestGhFailureFallback:
    def test_release_failure_yields_manual_steps_and_warning(
        self, publisher, tmp_path
    ):
        """gh was available but rejected the upload — we must leave the
        artifacts in place so the user can retry manually instead of
        silently losing their zip."""
        local = _make_tool(tmp_path)
        gh = _StubGh(
            available=True,
            raises=_StubGh.GhCliError("nope", stderr="repo not found"),
        )
        result = publisher.publish_github(
            _pkg_data(local), repo="ghost/repo", gh_cli_module=gh,
        )
        assert "release_url" not in result
        assert "manual_steps" in result
        assert os.path.exists(result["zip_path"])
        warnings = result.get("warnings") or []
        assert any("gh release create failed" in w for w in warnings)
        assert any("repo not found" in w for w in warnings)


class TestIdentityPersistence:
    def test_writes_namespace_name_back_into_source(self, publisher, tmp_path):
        """Mirror of the embedded-publish behaviour: successive publishes
        from this clone must converge on the same identity."""
        local = _make_tool(tmp_path)
        # Blow away the existing namespace so we can prove it's rewritten.
        pkg_json_path = os.path.join(local, "package.json")
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.pop("namespace", None)
        with open(pkg_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        gh = _StubGh(available=True)
        publisher.publish_github(
            _pkg_data(local),
            repo="mystudio/my_tool",
            gh_cli_module=gh,
        )
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["namespace"] == "mystudio"
        assert data["name"] == "my_tool"


class TestValidation:
    def test_missing_namespace_raises(self, publisher, tmp_path):
        local = _make_tool(tmp_path)
        data = _pkg_data(local)
        data["namespace"] = ""
        with pytest.raises(MissingNamespaceError):
            publisher.publish_github(data, repo="ghost/repo", gh_cli_module=_StubGh())

    def test_missing_local_path_raises(self, publisher, tmp_path):
        data = _pkg_data(str(tmp_path / "does-not-exist"))
        with pytest.raises(RuntimeError, match="File not found"):
            publisher.publish_github(data, repo="ghost/repo", gh_cli_module=_StubGh())
