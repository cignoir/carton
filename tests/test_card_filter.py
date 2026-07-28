"""Search and namespace folding must agree on what is on screen.

They used to write card visibility independently and whichever ran last
won: typing revealed cards inside a folded namespace, clearing the box
unfolded everything the user had put away, and filtering left namespace
headers standing over nothing.
"""

import types

import pytest

pytest.importorskip("pytestqt")

from carton.ui._namespace_grouping import arrow_glyph
from carton.ui.main_window import CartonWindow
from carton.ui.package_card import PackageCard


def _installed(pkg_id, namespace, name, display_name, tags=()):
    return {
        "namespace": namespace,
        "name": name,
        "display_name": display_name,
        "version": "1.0.0",
        "type": "python_package",
        "source": "local",
        "local_path": "/tmp/" + name,
        "tags": list(tags),
    }


PACKAGES = {
    "acme/rigger": _installed("acme/rigger", "acme", "rigger", "Rigger",
                              tags=["rig"]),
    "acme/exporter": _installed("acme/exporter", "acme", "exporter",
                                "Exporter", tags=["io"]),
    "studio/baker": _installed("studio/baker", "studio", "baker", "Baker",
                               tags=["bake"]),
}


@pytest.fixture
def window(qtbot):
    win = CartonWindow()
    qtbot.addWidget(win)
    win._install_manager = types.SimpleNamespace(
        get_installed_packages=lambda: PACKAGES,
    )
    win._catalogue_client = types.SimpleNamespace(
        get_packages=lambda: {},
        get_origin=lambda pkg_id: None,
    )
    win._build_published_map = lambda: {}
    # Render the My Tools root, which is the grouped (namespace tree) view.
    win._sidebar_selection = win._MYTOOLS_KEY
    win._rebuild_cards()
    return win


def _cards(win):
    return {c.pkg_id: c for c in win._iter_cards()}


def _headers(win):
    return dict(
        (ns, header) for ns, (header, _cards) in win._active_ns_groups.items()
    )


def _shown(widget):
    """Whether the widget would be drawn if the window were open.

    ``isVisible()`` is False for every child of a window that has never
    been shown, which is every window in a headless test run. What these
    tests care about is the explicit hide, and that is ``isHidden()``.
    """
    return not widget.isHidden()


class TestPackageCardMatching:
    """``qtbot`` is required even though only matches() is exercised:
    PackageCard is a QWidget, and constructing one without a running
    QApplication aborts the interpreter rather than raising."""

    def test_matches_internal_name(self, qtbot):
        card = PackageCard("acme/rigger", PACKAGES["acme/rigger"])
        qtbot.addWidget(card)
        assert card.matches("rigg")

    def test_matches_display_name_case_insensitively(self, qtbot):
        card = PackageCard("acme/rigger", PACKAGES["acme/rigger"])
        qtbot.addWidget(card)
        assert card.matches("RIGGER")

    def test_matches_tags(self, qtbot):
        card = PackageCard("acme/exporter", PACKAGES["acme/exporter"])
        qtbot.addWidget(card)
        assert card.matches("io")

    def test_empty_query_matches_everything(self, qtbot):
        card = PackageCard("acme/rigger", PACKAGES["acme/rigger"])
        qtbot.addWidget(card)
        assert card.matches("")
        assert card.matches("   ")

    def test_non_matching_query(self, qtbot):
        card = PackageCard("acme/rigger", PACKAGES["acme/rigger"])
        qtbot.addWidget(card)
        assert not card.matches("nothing-like-this")


class TestFilterRespectsFolding:
    def test_all_cards_visible_initially(self, window):
        cards = _cards(window)
        assert len(cards) == 3
        assert all(_shown(c) for c in cards.values())

    def test_folding_hides_only_that_namespace(self, window):
        window._toggle_mytools_group("acme")

        cards = _cards(window)
        assert not _shown(cards["acme/rigger"])
        assert not _shown(cards["acme/exporter"])
        assert _shown(cards["studio/baker"])

    def test_search_reveals_matches_inside_a_folded_namespace(self, window):
        """A hit the user cannot see reads as "no results"."""
        window._toggle_mytools_group("acme")

        window._search.setText("rigger")

        cards = _cards(window)
        assert _shown(cards["acme/rigger"])
        assert not _shown(cards["acme/exporter"])
        assert not _shown(cards["studio/baker"])

    def test_clearing_the_search_restores_the_fold(self, window):
        window._toggle_mytools_group("acme")
        window._search.setText("rigger")

        window._search.setText("")

        cards = _cards(window)
        assert not _shown(cards["acme/rigger"])
        assert not _shown(cards["acme/exporter"])
        assert _shown(cards["studio/baker"])

    def test_headers_without_matches_are_hidden(self, window):
        window._search.setText("baker")

        headers = _headers(window)
        assert not _shown(headers["acme"])
        assert _shown(headers["studio"])

    def test_headers_return_when_the_search_clears(self, window):
        window._search.setText("baker")
        window._search.setText("")

        headers = _headers(window)
        assert all(_shown(h) for h in headers.values())

    def test_header_arrow_tracks_what_is_shown(self, window):
        headers = _headers(window)
        assert headers["acme"].text().startswith(arrow_glyph(True))

        window._toggle_mytools_group("acme")
        assert headers["acme"].text().startswith(arrow_glyph(False))

        # A search expands to show its hits, so the arrow must not keep
        # claiming the namespace is folded.
        window._search.setText("rigger")
        assert headers["acme"].text().startswith(arrow_glyph(True))

        window._search.setText("")
        assert headers["acme"].text().startswith(arrow_glyph(False))

    def test_folding_while_searching_does_not_reveal_non_matches(self, window):
        window._search.setText("rigger")

        window._toggle_mytools_group("acme")

        cards = _cards(window)
        assert not _shown(cards["acme/exporter"])

    def test_rebuild_reapplies_the_active_search(self, window):
        """Installing or publishing rebuilds the list mid-search."""
        window._search.setText("baker")

        window._rebuild_cards()

        cards = _cards(window)
        assert _shown(cards["studio/baker"])
        assert not _shown(cards["acme/rigger"])

    def test_rebuild_reapplies_the_fold(self, window):
        window._toggle_mytools_group("acme")

        window._rebuild_cards()

        cards = _cards(window)
        assert not _shown(cards["acme/rigger"])
        assert _shown(cards["studio/baker"])


class TestFlatView:
    def test_namespace_scoped_view_filters_without_headers(self, qtbot):
        win = CartonWindow()
        qtbot.addWidget(win)
        win._install_manager = types.SimpleNamespace(
            get_installed_packages=lambda: PACKAGES,
        )
        win._catalogue_client = types.SimpleNamespace(
            get_packages=lambda: {}, get_origin=lambda pkg_id: None,
        )
        win._build_published_map = lambda: {}
        win._sidebar_selection = win._MYTOOLS_NS_PREFIX + "acme"
        win._rebuild_cards()

        assert win._active_ns_groups == {}

        win._search.setText("exporter")
        cards = _cards(win)
        assert _shown(cards["acme/exporter"])
        assert not _shown(cards["acme/rigger"])
