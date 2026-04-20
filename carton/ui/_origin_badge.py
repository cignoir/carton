"""Helper for the v5.0 origin-verification (pinned/unpinned) badge.

The badge answers a Library-level question: **can we trust the source
of this artifact?** — separate from the install-time ``verified`` mark
(which only says "SHA256 matched at download"). A pinned origin means
the catalogue / Release SHA256SUMS authoritatively names the bytes
that should arrive; an unpinned origin means we're TOFU-ing on first
download (typical of GitHub auto-generated archives). ``strict_verify``
flips unpinned into install-refused.

The decision is pure logic over ``pkg_data``, separated from the Qt
layer so it can be unit-tested without a running QApplication.
Returning ``None`` means "no badge" — e.g. legacy v0.4 registry
packages that pre-date the concept.
"""


# What counts as "the version we're currently judging":
#
# - If the user has already installed it, we judge that version
#   (they might reinstall to verify signed source).
# - Otherwise we look at ``latest_version`` (Library / catalogue
#   browsing — decision is for the install-about-to-happen).
#
# Both keys come from the ``pkg_data`` dict CatalogueClient hands
# the UI; callers don't need to resolve it themselves.
def _pick_version(pkg_data, installed_version):
    if installed_version:
        return installed_version
    return pkg_data.get("latest_version") or ""


# The truthy ``_pinned`` flag is attached by
# :meth:`CatalogueClient._project_github_versions` for every github
# version. Embedded origins don't attach it (their sha256 is always
# authoritative by construction) — we treat a missing flag on an
# embedded version as pinned. Legacy v0.4 packages without origin
# metadata return ``None`` so the caller shows no badge at all.
def resolve_origin_verification(pkg_data, installed_version=None):
    """Decide whether and how to show the origin-verification badge.

    Args:
        pkg_data: Legacy-shape dict produced by CatalogueClient /
            RegistryClient (``versions`` + ``_origin`` + per-version
            ``_pinned`` mirror flag).
        installed_version: The user's installed version, if any. When
            set, we judge that specific version; otherwise we look at
            ``latest_version``.

    Returns:
        A dict ``{"state", "text_key", "tooltip_key", "glyph"}`` when
        the badge applies, or ``None`` when the package pre-dates the
        origin model (pure v0.4 registry entry with no origin info) so
        the caller can render nothing rather than a guess.

        * ``state`` — ``"pinned"`` or ``"unpinned"``.
        * ``text_key`` / ``tooltip_key`` — i18n keys for
          ``carton.ui.i18n.t``; ``glyph`` is the leading emoji.
    """
    origin = pkg_data.get("_origin") or {}
    origin_type = origin.get("type")
    if not origin_type:
        # No origin info at all — v0.4 entry, or a package that slipped
        # through without being projected by CatalogueClient. Silent.
        return None

    version = _pick_version(pkg_data, installed_version)
    versions = pkg_data.get("versions") or {}
    ver_info = versions.get(version) or {}

    if "_pinned" in ver_info:
        pinned = bool(ver_info["_pinned"])
    elif origin_type == "embedded":
        # Embedded origins don't stamp ``_pinned`` because their
        # sha256 is mandatory by catalogue shape — treat as pinned.
        pinned = True
    else:
        # github/url/local origins without ``_pinned`` likely come from
        # a version that failed to resolve; don't invent a verdict.
        return None

    if pinned:
        return {
            "state": "pinned",
            "text_key": "origin_verified_badge",
            "tooltip_key": "origin_verified_tooltip",
            "glyph": "\U0001f512",  # 🔒
        }
    return {
        "state": "unpinned",
        "text_key": "origin_unverified_badge",
        "tooltip_key": "origin_unverified_tooltip",
        "glyph": "\u26a0",  # ⚠
    }
