"""Tests for the exception → user-facing message translator.

Verifies:
  * Each core exception class is routed to its expected body i18n key.
  * Substring-based subcategorization (DownloadError, InstallError,
    GhCliError) picks the right branch.
  * ``operation`` → title key mapping is correct for every supported value.
  * Both ``en`` and ``ja`` i18n tables contain every key referenced by
    the classifier (catching missing translations before they hit users).
  * The original exception message is preserved verbatim in ``detail``.
"""

import pytest

from carton.core.config import InstallDirChangeError
from carton.core.downloader import DownloadError
from carton.core.gh_cli import GhCliError
from carton.core.github_api import GithubApiError
from carton.core.identity import InvalidIdentityError
from carton.core.installer import InstallError
from carton.core.origins.base import OriginError
from carton.core.profile import InvalidProfileError
from carton.core.publisher import (
    InvalidPythonPackageLayoutError,
    MissingNamespaceError,
)
from carton.ui.error_messages import (
    UserMessage,
    _classify,
    user_facing,
)
from carton.ui import i18n


@pytest.fixture(autouse=True)
def _reset_language():
    """Tests may switch languages; restore the default afterwards."""
    before = i18n.get_language()
    yield
    i18n.set_language(before)


# --- Download subcategorization ---------------------------------------------

@pytest.mark.parametrize("message,expected_body", [
    ("unpinned source rejected (strict_verify is on): foo",
     "err_download_strict_policy"),
    ("SHA256 mismatch", "err_download_integrity"),
    ("TOFU sha256 compute failed: disk full",
     "err_download_integrity"),
    ("Insufficient disk space: need 100MB, have 1MB",
     "err_download_disk"),
    ("File not found: /x/y.zip", "err_download_url_missing"),
    ("artifact has no URL", "err_download_url_missing"),
    ("Download failed after 3 retries: timeout",
     "err_download_network"),
])
def test_download_error_subcategorization(message, expected_body):
    body_key, _ = _classify(DownloadError(message))
    assert body_key == expected_body


# --- Install subcategorization ----------------------------------------------

@pytest.mark.parametrize("message,expected_body", [
    ("Corrupt zip — bad entry: foo", "err_install_zip_corrupt"),
    ("Invalid or corrupt package zip: bad magic",
     "err_install_zip_corrupt"),
    ("Failed to extract package: permission denied",
     "err_install_extract_failed"),
    ("Handler install failed: boom",
     "err_install_handler_failed"),
    ("Failed to persist installed.json: disk full",
     "err_install_persist_failed"),
    ("Some other thing", "err_install_generic"),
])
def test_install_error_subcategorization(message, expected_body):
    body_key, _ = _classify(InstallError(message))
    assert body_key == expected_body


# --- GhCli subcategorization ------------------------------------------------

@pytest.mark.parametrize("message,expected_body", [
    ("gh CLI not found on PATH", "err_gh_cli_missing"),
    ("asset not found: SHA256SUMS", "err_gh_asset_missing"),
    ("gh invocation failed: timeout", "err_gh_generic"),
])
def test_gh_cli_error_subcategorization(message, expected_body):
    body_key, _ = _classify(GhCliError(message))
    assert body_key == expected_body


# --- One-shot class-based routing -------------------------------------------

@pytest.mark.parametrize("exc,expected_body", [
    (GithubApiError("boom"), "err_github_api_generic"),
    (OriginError("bad shape"), "err_origin_malformed"),
    (InvalidIdentityError("bad"), "err_identity_invalid"),
    (InvalidProfileError("bad"), "err_profile_invalid"),
    (InstallDirChangeError("bad"), "err_install_dir_change"),
    (MissingNamespaceError("bad"), "err_publish_namespace_required"),
    (RuntimeError("something unexpected"), "err_unknown"),
    (ValueError("also unexpected"), "err_unknown"),
])
def test_class_based_routing(exc, expected_body):
    body_key, _ = _classify(exc)
    assert body_key == expected_body


def test_invalid_python_package_layout_routes_to_publish_invalid_layout():
    # This exception takes (local_path, name) kwargs in __init__, so it
    # gets its own test rather than a parametrize row.
    exc = InvalidPythonPackageLayoutError("/some/path", "mytool")
    body_key, _ = _classify(exc)
    assert body_key == "err_publish_invalid_layout"


# --- Operation → title mapping ----------------------------------------------

@pytest.mark.parametrize("operation,expected_title_key", [
    ("install", "install_error"),
    ("publish", "publish_error"),
    ("unpublish", "unpublish_error"),
    ("update", "update_error"),
    ("register", "register_error"),
    ("launch", "launch_error"),
])
def test_operation_title_mapping(operation, expected_title_key):
    msg = user_facing(RuntimeError("x"), operation=operation)
    assert msg.title == i18n.t(expected_title_key)


def test_unknown_operation_uses_generic_title():
    msg = user_facing(RuntimeError("x"), operation=None)
    assert msg.title == i18n.t("err_title_generic")


def test_unrecognized_operation_falls_back_to_generic():
    msg = user_facing(RuntimeError("x"), operation="unknown_op_xyz")
    assert msg.title == i18n.t("err_title_generic")


# --- UserMessage contract ---------------------------------------------------

def test_user_message_preserves_original_detail():
    exc = DownloadError("SHA256 mismatch")
    msg = user_facing(exc, operation="install")
    assert msg.detail == "SHA256 mismatch"


def test_user_message_has_hint_when_classifier_returns_one():
    exc = DownloadError("SHA256 mismatch")
    msg = user_facing(exc, operation="install")
    assert msg.hint  # non-empty


def test_user_message_body_is_translated_not_key():
    exc = DownloadError("SHA256 mismatch")
    i18n.set_language("en")
    msg = user_facing(exc, operation="install")
    # The body should be the translated string, not the key itself.
    assert msg.body != "err_download_integrity"
    assert "integrity" in msg.body.lower()


def test_user_message_body_is_japanese_when_language_is_ja():
    exc = DownloadError("SHA256 mismatch")
    i18n.set_language("ja")
    msg = user_facing(exc, operation="install")
    assert msg.body != "err_download_integrity"
    # Must contain at least one non-ASCII character (Japanese).
    assert any(ord(c) > 127 for c in msg.body)


# --- i18n coverage ----------------------------------------------------------

def _all_keys_referenced_by_classifier():
    """Collect every i18n key the classifier can produce, across all
    exception shapes. We do this by invoking ``_classify`` on synthetic
    exceptions that exercise each branch."""
    samples = [
        # DownloadError branches
        DownloadError("unpinned source rejected: x"),
        DownloadError("SHA256 mismatch"),
        DownloadError("TOFU sha256 compute failed"),
        DownloadError("Insufficient disk space"),
        DownloadError("File not found"),
        DownloadError("artifact has no URL"),
        DownloadError("Download failed after 3 retries"),
        # InstallError branches
        InstallError("Corrupt zip"),
        InstallError("Invalid or corrupt package zip"),
        InstallError("Failed to extract"),
        InstallError("Handler install failed"),
        InstallError("Failed to persist"),
        InstallError("something else"),
        # GhCliError branches
        GhCliError("gh CLI not found on PATH"),
        GhCliError("asset not found"),
        GhCliError("gh invocation failed"),
        # Other classes
        GithubApiError("x"),
        OriginError("x"),
        InvalidIdentityError("x"),
        InvalidProfileError("x"),
        InstallDirChangeError("x"),
        MissingNamespaceError("x"),
        InvalidPythonPackageLayoutError("/p", "n"),
        RuntimeError("x"),  # unknown branch
    ]
    keys = set()
    for exc in samples:
        body, hint = _classify(exc)
        keys.add(body)
        if hint:
            keys.add(hint)
    # Also include the operation titles.
    keys.update([
        "install_error", "publish_error", "unpublish_error",
        "update_error", "register_error", "launch_error",
        "err_title_generic",
    ])
    return keys


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_all_classifier_keys_exist_in_language(lang):
    keys = _all_keys_referenced_by_classifier()
    strings = i18n._STRINGS[lang]
    missing = [k for k in keys if k not in strings]
    assert not missing, (
        "Missing {} translations for keys: {}".format(lang, missing)
    )


def test_user_message_is_user_message_instance():
    msg = user_facing(RuntimeError("x"), operation="install")
    assert isinstance(msg, UserMessage)
    assert hasattr(msg, "title")
    assert hasattr(msg, "body")
    assert hasattr(msg, "hint")
    assert hasattr(msg, "detail")
