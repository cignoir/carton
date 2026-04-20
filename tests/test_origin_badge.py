"""Tests for the v5.0 origin-verification badge resolver.

Step 4-B: decides whether a Library card shows 🔒 verified-source or
⚠ unverified-source. Pure logic — isolates the Qt layer from the
decision so pytest can cover it without a running QApplication.

Invariants:

* No origin info (legacy v0.4 shape) → ``None`` (caller renders
  nothing rather than guessing).
* Embedded origin without explicit ``_pinned`` → ``"pinned"`` (embedded
  catalogues' sha256 is mandatory by schema).
* Github origin with ``_pinned: True`` → ``"pinned"``; ``False`` →
  ``"unpinned"``.
* Github origin without the flag → ``None`` (version failed to resolve;
  don't invent a verdict).
* ``installed_version`` takes precedence over ``latest_version`` for
  the per-version lookup.
"""

from carton.ui._origin_badge import resolve_origin_verification


def _pkg(origin_type, versions, latest_version="1.0.0"):
    return {
        "latest_version": latest_version,
        "versions": versions,
        "_origin": {"type": origin_type},
    }


class TestLegacyShape:
    def test_no_origin_returns_none(self):
        pkg = {"latest_version": "1.0.0", "versions": {"1.0.0": {}}}
        assert resolve_origin_verification(pkg) is None

    def test_empty_origin_returns_none(self):
        pkg = {"latest_version": "1.0.0", "versions": {"1.0.0": {}},
               "_origin": {}}
        assert resolve_origin_verification(pkg) is None


class TestEmbeddedOrigin:
    def test_embedded_defaults_to_pinned(self):
        """No ``_pinned`` flag on embedded versions — treat as pinned."""
        pkg = _pkg("embedded", {"1.0.0": {"sha256": "a" * 64}})
        badge = resolve_origin_verification(pkg)
        assert badge is not None
        assert badge["state"] == "pinned"
        assert badge["text_key"] == "origin_verified_badge"
        assert badge["glyph"] == "\U0001f512"

    def test_embedded_explicit_pinned_false_respected(self):
        """If a future producer explicitly stamps _pinned=False we
        honour it rather than hard-assuming embedded."""
        pkg = _pkg("embedded", {"1.0.0": {"_pinned": False}})
        badge = resolve_origin_verification(pkg)
        assert badge["state"] == "unpinned"


class TestGithubOrigin:
    def test_pinned_true(self):
        pkg = _pkg("github", {"1.0.0": {"_pinned": True, "sha256": "a" * 64}})
        badge = resolve_origin_verification(pkg)
        assert badge["state"] == "pinned"

    def test_pinned_false(self):
        pkg = _pkg("github", {"1.0.0": {"_pinned": False}})
        badge = resolve_origin_verification(pkg)
        assert badge["state"] == "unpinned"
        assert badge["text_key"] == "origin_unverified_badge"
        assert badge["glyph"] == "\u26a0"

    def test_missing_flag_returns_none(self):
        """github version without the flag didn't resolve — silent."""
        pkg = _pkg("github", {"1.0.0": {}})
        assert resolve_origin_verification(pkg) is None


class TestVersionSelection:
    def test_uses_installed_version_when_given(self):
        pkg = _pkg("github", {
            "1.0.0": {"_pinned": False},
            "2.0.0": {"_pinned": True},
        }, latest_version="2.0.0")
        # Installed v1.0.0 (unpinned) — badge reflects *that* version,
        # not latest.
        badge = resolve_origin_verification(pkg, installed_version="1.0.0")
        assert badge["state"] == "unpinned"

    def test_falls_back_to_latest_without_installed(self):
        pkg = _pkg("github", {
            "1.0.0": {"_pinned": False},
            "2.0.0": {"_pinned": True},
        }, latest_version="2.0.0")
        badge = resolve_origin_verification(pkg)
        assert badge["state"] == "pinned"


class TestOtherOriginTypes:
    def test_url_without_pinned_flag_silent(self):
        pkg = _pkg("url", {"1.0.0": {}})
        assert resolve_origin_verification(pkg) is None

    def test_url_with_pinned_true(self):
        pkg = _pkg("url", {"1.0.0": {"_pinned": True}})
        badge = resolve_origin_verification(pkg)
        assert badge["state"] == "pinned"
