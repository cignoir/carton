"""Thin wrapper around the GitHub ``gh`` CLI.

Used by :mod:`carton.core.publisher`'s github-origin publish path to
create Releases and upload assets. Keeping the subprocess plumbing here
(instead of inline in the publisher) means tests can mock one surface
and the publisher stays focused on the policy layer.

Everything here is best-effort: any non-zero ``gh`` exit, missing binary,
or unauthenticated state raises :class:`GhCliError`. The publisher
catches that and falls back to emitting manual-step instructions for the
user to run themselves.
"""

import os
import shutil
import subprocess


class GhCliError(RuntimeError):
    """Raised when the ``gh`` CLI is unavailable or returns a non-zero exit.

    ``stderr`` carries gh's own error message when available so callers
    can surface something actionable ("not logged in", "repo not found",
    etc.) instead of a generic failure.
    """

    def __init__(self, message, stderr=""):
        super().__init__(message)
        self.stderr = stderr


def is_available():
    """Return True if ``gh`` is on PATH and reports a logged-in user.

    We intentionally call ``gh auth status`` — a plain ``which gh`` would
    pass for installs that haven't been authenticated yet, and the
    Release-create call would then fail in a confusing way. Checking
    auth status upfront lets the UI hint "run ``gh auth login`` first"
    before the user clicks publish.
    """
    if shutil.which("gh") is None:
        return False
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def create_release(repo, tag, title="", notes="", assets=None,
                   draft=False, prerelease=False, cwd=None):
    """Create a GitHub Release on ``repo`` with the given ``tag`` and assets.

    Args:
        repo: ``"owner/name"`` slug.
        tag: Release tag (e.g. ``"v1.0.0"``). Must already exist as a git
            tag on the remote — ``gh release create`` creates tags from
            a ref only with the ``--target`` flag, which we intentionally
            don't expose here to keep the contract simple.
        title: Release title. Defaults to the tag.
        notes: Release body (markdown).
        assets: List of local filesystem paths to upload as release
            assets. Paths must exist on disk before calling.
        draft: Publish as a draft.
        prerelease: Flag the release as a prerelease.
        cwd: Optional working directory for the subprocess (useful when
            the publisher operates on the source clone).

    Returns:
        Stripped stdout from ``gh`` — typically the Release URL.

    Raises:
        GhCliError: When ``gh`` is unavailable or returns non-zero.
    """
    if shutil.which("gh") is None:
        raise GhCliError("gh CLI not found on PATH")

    cmd = ["gh", "release", "create", tag, "--repo", repo]
    if title:
        cmd += ["--title", title]
    # ``gh`` reads empty notes as "open editor" — force non-interactive
    # mode with an explicit empty-string notes value via --notes so we
    # never block on a user-facing editor when called from the UI.
    cmd += ["--notes", notes or ""]
    if draft:
        cmd.append("--draft")
    if prerelease:
        cmd.append("--prerelease")

    for asset in assets or []:
        if not os.path.exists(asset):
            raise GhCliError("asset not found: {}".format(asset))
        cmd.append(asset)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=cwd,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GhCliError("gh invocation failed: {}".format(e))

    if result.returncode != 0:
        raise GhCliError(
            "gh release create failed (exit {})".format(result.returncode),
            stderr=(result.stderr or "").strip(),
        )
    return (result.stdout or "").strip()


def build_manual_instructions(repo, tag, assets, notes=""):
    """Return a human-readable fallback for when ``gh`` isn't usable.

    Called by the publisher when :func:`is_available` returns False so
    the UI can show the user the exact steps they'd otherwise automate.
    Stable, copy-pasteable — don't decorate with styling here.
    """
    lines = [
        "GitHub CLI ('gh') is not available. Run these steps manually:",
        "",
        "  1. Tag the release on your local clone:",
        "       git tag {tag}".format(tag=tag),
        "       git push origin {tag}".format(tag=tag),
        "",
        "  2. Create the Release on GitHub (web UI or gh once installed):",
        "       gh release create {tag} --repo {repo} \\".format(
            tag=tag, repo=repo,
        ),
    ]
    for asset in assets or []:
        lines.append("         {}".format(asset))
    if notes:
        lines.append("       --notes {!r}".format(notes))
    return "\n".join(lines)
