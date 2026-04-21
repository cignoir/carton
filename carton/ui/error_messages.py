"""Translate core exceptions into user-facing messages.

Core raises technical exceptions; UI shouldn't dump them raw to users
who may not know what "TOFU", "strict_verify", "handler", or "PATH" mean.
This module is the single place that maps an exception into a
:class:`UserMessage` (title, body, hint, detail) suitable for a
``QMessageBox``.

Why this layer exists:
    - Core stays UI-agnostic — no i18n or presentation concerns leak in.
    - New exception types or sub-cases only need edits here.
    - Tests for message mapping don't need Qt.
"""

from carton.ui.i18n import t

# Core exception imports are narrow: we don't want to couple error_messages
# to the full core surface, just to the exception symbols we classify.
from carton.core.downloader import DownloadError
from carton.core.installer import InstallError
from carton.core.publisher import (
    VersionConflictError,
    MissingNamespaceError,
    InvalidPythonPackageLayoutError,
    RemoteMirrorMissingError,
)
from carton.core.gh_cli import GhCliError
from carton.core.github_api import GithubApiError
from carton.core.origins.base import OriginError
from carton.core.identity import InvalidIdentityError
from carton.core.profile import InvalidProfileError
from carton.core.config import InstallDirChangeError


_OPERATION_TITLE_KEYS = {
    "install": "install_error",
    "publish": "publish_error",
    "unpublish": "unpublish_error",
    "update": "update_error",
    "register": "register_error",
    "launch": "launch_error",
}


class UserMessage(object):
    """A user-facing error message split into QMessageBox-friendly parts.

    Attributes:
        title: Dialog window title (e.g. "Install Error").
        body: One-sentence main message in plain language.
        hint: Actionable guidance (e.g. "Check your network and try again").
              Empty string if no specific hint applies.
        detail: The original ``str(exception)`` for the Details pane —
                preserved verbatim so it stays useful for bug reports.
    """

    __slots__ = ("title", "body", "hint", "detail")

    def __init__(self, title, body, hint="", detail=""):
        self.title = title
        self.body = body
        self.hint = hint
        self.detail = detail


def user_facing(exc, operation=None):
    """Translate an exception into a :class:`UserMessage`.

    Args:
        exc: Exception raised by core.
        operation: ``"install"`` / ``"publish"`` / ``"unpublish"`` /
            ``"update"`` / ``"register"`` / ``"launch"``. Used to pick the
            dialog title. ``None`` falls back to a generic title.

    Returns:
        A :class:`UserMessage`. Never ``None``.
    """
    title = _title_for(operation)
    body_key, hint_key = _classify(exc)
    body = t(body_key)
    hint = t(hint_key) if hint_key else ""
    detail = str(exc)
    return UserMessage(title=title, body=body, hint=hint, detail=detail)


def show_error(parent, exc, operation=None):
    """Display an error dialog for ``exc`` using native QMessageBox slots.

    Kept thin on purpose — ``user_facing()`` does the mapping, this just
    wires the parts into setText / setInformativeText / setDetailedText
    so the Details pane is collapsed by default.
    """
    # Lazy import so tests can exercise user_facing() without Qt.
    from carton.ui.compat import QtWidgets

    msg = user_facing(exc, operation=operation)
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle(msg.title)
    box.setText(msg.body)
    if msg.hint:
        box.setInformativeText(msg.hint)
    if msg.detail and msg.detail != msg.body:
        box.setDetailedText(msg.detail)
    box.setStandardButtons(QtWidgets.QMessageBox.Ok)
    box.exec_()


def _title_for(operation):
    key = _OPERATION_TITLE_KEYS.get(operation)
    if key:
        return t(key)
    return t("err_title_generic")


def _classify(exc):
    """Return ``(body_key, hint_key)`` i18n keys for an exception.

    Order matters: more specific subclasses must be checked before their
    parents. ``hint_key`` may be ``""`` to indicate no hint.
    """
    # --- Download errors: subcategorize by message substring.
    # DownloadError only carries a message string; we don't want to
    # redesign core to add error codes just for UI display, so we do a
    # narrow substring match here. The substrings are anchored to the
    # literal strings raised in downloader.py.
    if isinstance(exc, DownloadError):
        s = str(exc)
        if "unpinned source rejected" in s:
            return "err_download_strict_policy", "err_download_strict_policy_hint"
        if "SHA256 mismatch" in s or "TOFU sha256" in s:
            return "err_download_integrity", "err_download_integrity_hint"
        if "Insufficient disk space" in s:
            return "err_download_disk", "err_download_disk_hint"
        if s.startswith("File not found") or "no URL" in s:
            return "err_download_url_missing", "err_download_url_missing_hint"
        # Generic fallback (network errors, unexpected transport failures).
        return "err_download_network", "err_download_network_hint"

    # --- Install errors.
    if isinstance(exc, InstallError):
        s = str(exc)
        if "Corrupt zip" in s or "Invalid or corrupt package zip" in s:
            return "err_install_zip_corrupt", "err_install_zip_corrupt_hint"
        if "Failed to extract" in s:
            return "err_install_extract_failed", "err_install_extract_failed_hint"
        if "Handler install failed" in s:
            return "err_install_handler_failed", "err_install_handler_failed_hint"
        if "Failed to persist" in s:
            return "err_install_persist_failed", "err_install_persist_failed_hint"
        return "err_install_generic", "err_install_generic_hint"

    # --- Publish-related.
    # VersionConflictError needs the version number formatted in, so it
    # can't share the generic pipeline — callers that want that specific
    # message should use the existing publish_already_published key.
    if isinstance(exc, MissingNamespaceError):
        return "err_publish_namespace_required", "err_publish_namespace_required_hint"
    if isinstance(exc, InvalidPythonPackageLayoutError):
        return "err_publish_invalid_layout", "err_publish_invalid_layout_hint"
    # RemoteMirrorMissingError has its own UX branch (_handle_missing_mirror);
    # if it ever falls through here, at least surface something readable.

    # --- GitHub CLI and API.
    if isinstance(exc, GhCliError):
        s = str(exc)
        if "not found on PATH" in s:
            return "err_gh_cli_missing", "err_gh_cli_missing_hint"
        if "asset not found" in s:
            return "err_gh_asset_missing", "err_gh_asset_missing_hint"
        return "err_gh_generic", "err_gh_generic_hint"
    if isinstance(exc, GithubApiError):
        return "err_github_api_generic", "err_github_api_generic_hint"

    # --- Structural / config.
    if isinstance(exc, OriginError):
        return "err_origin_malformed", "err_origin_malformed_hint"
    if isinstance(exc, InvalidIdentityError):
        return "err_identity_invalid", "err_identity_invalid_hint"
    if isinstance(exc, InvalidProfileError):
        return "err_profile_invalid", "err_profile_invalid_hint"
    if isinstance(exc, InstallDirChangeError):
        return "err_install_dir_change", "err_install_dir_change_hint"

    # --- Fallback for anything we didn't classify.
    return "err_unknown", "err_unknown_hint"
