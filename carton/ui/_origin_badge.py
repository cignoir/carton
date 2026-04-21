"""Helper for the v5.0 origin-verification (pinned) badge.

The badge answers a Library-level question: **is the source of this
artifact signed?** — separate from the install-time ``verified`` mark
(which only says "SHA256 matched at download"). A pinned origin means
the catalogue / Release SHA256SUMS authoritatively names the bytes
that should arrive; an unpinned origin means we're TOFU-ing on first
download (typical of GitHub auto-generated archives). ``strict_verify``
flips unpinned into install-refused.

UX convention — mirror the existing ``verified`` mark on installed
packages: show a single ✓ glyph only when the positive state is true.
Silence on the unpinned side. That keeps the card quiet (no loud pills
shouting "Verified source" / "Unverified source"); tooltip on the
pinned glyph still carries the detail for curious users. Unpinned-ness
surfaces at install time (strict_verify error), not as a pre-install
warning pill.

The decision is pure logic over ``pkg_data``, separated from the Qt
layer so it can be unit-tested without a running QApplication.
Returning ``None`` means "no badge" — either a legacy v0.4 package
without origin info, or an unpinned origin (the UX is deliberately
silent on the negative state).
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
        pkg_data: Legacy-shape dict produced by CatalogueClient
            (``versions`` + ``_origin`` + per-version ``_pinned``
            mirror flag).
        installed_version: The user's installed version, if any. When
            set, we judge that specific version; otherwise we look at
            ``latest_version``.

    Returns:
        A dict ``{"state", "tooltip_key", "glyph"}`` when the pinned
        state applies, or ``None`` otherwise — either because the
        package is unpinned (silent by design), or because there is no
        origin info at all (legacy v0.4 entry).

        * ``state`` — currently always ``"pinned"`` when non-None.
        * ``tooltip_key`` — i18n key for ``carton.ui.i18n.t``.
        * ``glyph`` — single checkmark glyph ``"\u2713"``, matching the
          existing install-time ``verified`` mark so the card's
          visual grammar stays consistent.
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
            "tooltip_key": "origin_verified_tooltip",
            "glyph": "\u2713",  # ✓ — matches the existing verified mark
        }
    # Unpinned: deliberately silent. strict_verify will refuse the
    # install if the user cares; the pre-install Library card stays
    # quiet rather than shouting "Unverified source".
    return None
