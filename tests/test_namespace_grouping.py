"""Tests for ``carton.ui._namespace_grouping``.

Step 4-B extracts the non-Qt pieces of the sidebar grouping logic so
they can be covered without a QApplication and re-used by the Library
sidebar migration (next sub-step).

Invariants:

* ``group_by_namespace`` is an *adjacent* split, not a re-sort —
  items that share a namespace but aren't contiguous in the input
  produce separate groups (caller's sort responsibility).
* Empty / missing namespace collapses to ``""`` so the caller can
  render a single "no namespace" bucket consistently.
* ``toggle_collapsed`` mutates the provided set in place and returns
  the *new* visibility (True = now visible = expanded).
* ``arrow_glyph`` centralises the glyph choice so initial header
  construction and the toggle path can't drift apart.
"""

from carton.ui._namespace_grouping import (
    arrow_glyph,
    group_by_namespace,
    toggle_collapsed,
)


def _items(pairs):
    """Expand ``[(pkg_id, ns)]`` into the full pkg_data shape tests need."""
    return [(pid, {"namespace": ns}) for pid, ns in pairs]


class TestGroupByNamespace:
    def test_empty_input(self):
        assert group_by_namespace([]) == []

    def test_single_namespace(self):
        result = group_by_namespace(_items([
            ("studio/a", "studio"),
            ("studio/b", "studio"),
        ]))
        assert result == [("studio", [
            ("studio/a", {"namespace": "studio"}),
            ("studio/b", {"namespace": "studio"}),
        ])]

    def test_multiple_namespaces(self):
        result = group_by_namespace(_items([
            ("a/one", "a"),
            ("b/one", "b"),
            ("b/two", "b"),
            ("c/one", "c"),
        ]))
        ns_keys = [ns for ns, _ in result]
        assert ns_keys == ["a", "b", "c"]
        counts = [len(items) for _, items in result]
        assert counts == [1, 2, 1]

    def test_missing_namespace_collapses_to_empty_string(self):
        result = group_by_namespace([
            ("bare_tool", {}),                 # no namespace key at all
            ("also_bare", {"namespace": None}),  # explicit None
            ("also_bare_again", {"namespace": ""}),
        ])
        assert len(result) == 1
        assert result[0][0] == ""
        assert len(result[0][1]) == 3

    def test_case_normalised(self):
        """Mixed-case ns entries collapse to a single lowercased bucket."""
        result = group_by_namespace(_items([
            ("a/one", "Studio"),
            ("a/two", "studio"),
            ("a/three", "STUDIO"),
        ]))
        assert len(result) == 1
        assert result[0][0] == "studio"

    def test_adjacent_split_non_contiguous_input(self):
        """Unsorted input produces as many groups as runs — documents
        the caller's sort responsibility, not a bug in the helper."""
        result = group_by_namespace(_items([
            ("a/one", "a"),
            ("b/one", "b"),
            ("a/two", "a"),  # same ns as the first but non-adjacent
        ]))
        assert [ns for ns, _ in result] == ["a", "b", "a"]

    def test_preserves_input_order_within_group(self):
        pairs = [
            ("a/three", "a"),
            ("a/one", "a"),
            ("a/two", "a"),
        ]
        result = group_by_namespace(_items(pairs))
        inner = result[0][1]
        assert [pid for pid, _ in inner] == ["a/three", "a/one", "a/two"]


class TestToggleCollapsed:
    def test_adds_when_absent_returns_not_visible(self):
        s = set()
        visible = toggle_collapsed(s, "studio")
        assert visible is False
        assert "studio" in s

    def test_removes_when_present_returns_visible(self):
        s = {"studio"}
        visible = toggle_collapsed(s, "studio")
        assert visible is True
        assert "studio" not in s

    def test_independent_namespaces(self):
        """Toggling one ns doesn't touch others."""
        s = {"a"}
        toggle_collapsed(s, "b")
        assert s == {"a", "b"}

    def test_double_toggle_restores(self):
        s = set()
        toggle_collapsed(s, "x")
        toggle_collapsed(s, "x")
        assert s == set()


class TestArrowGlyph:
    def test_visible_is_down_arrow(self):
        assert arrow_glyph(True) == "\u25bc"

    def test_collapsed_is_right_arrow(self):
        assert arrow_glyph(False) == "\u25b6"

    def test_glyphs_differ(self):
        """Sanity — guards against a future typo collapsing both
        states to the same character."""
        assert arrow_glyph(True) != arrow_glyph(False)
