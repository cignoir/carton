"""Pure helpers for namespace-tree rendering in the sidebar.

Step 4-B extracts the non-Qt portion of the My Tools namespace grouping
logic so the same primitives can drive the Library sidebar as well.
Widget construction stays in ``main_window`` — the helpers here only
decide *what* to group and toggle, not *how* to draw it.

Callers in the alias period:

* ``main_window._rebuild_cards`` — My Tools card list (per-namespace
  header + cards, collapsible).
* ``main_window._build_sidebar_registry_section`` — Library sidebar
  once Step 4-B migrates it to namespace-tree display (second bullet
  of the plan's Step 4-B section).

The functions are deliberately small and free of Qt imports so pytest
can cover the decision logic without a QApplication.
"""


# Adjacent-group split, not a re-sort. The caller is expected to have
# already sorted ``items`` — otherwise items that happen to share a
# namespace but sit non-contiguously produce two separate groups.
# This matches how ``_collect_mytools_items`` already sorts by
# (namespace, display_name) before handing us the list.
def group_by_namespace(sorted_items):
    """Split pre-sorted ``(pkg_id, pkg_data)`` into consecutive same-ns groups.

    Args:
        sorted_items: Iterable yielding ``(pkg_id, pkg_data)`` tuples
            sorted such that same-namespace items are adjacent.
            ``pkg_data["namespace"]`` is case-normalised to lowercase;
            missing or falsy values collapse to ``""`` (rendered as
            "no namespace" by the caller).

    Returns:
        A list of ``(ns_key, [items...])`` tuples in the order the
        groups first appeared. ``ns_key`` is the lowercase normalised
        namespace string; within each group, items keep their input
        order. An empty input yields an empty list.
    """
    # Sentinel object — distinct from any plausible ns string — so the
    # very first item always triggers a new-group branch.
    _START = object()
    groups = []
    current_ns = _START
    current_group = None
    for pkg_id, pkg_data in sorted_items:
        ns = (pkg_data.get("namespace") or "").strip().lower()
        if ns != current_ns:
            current_ns = ns
            current_group = []
            groups.append((ns, current_group))
        current_group.append((pkg_id, pkg_data))
    return groups


# Collapse state is a mutating set on the main_window; isolating the
# flip here means the toggle handler shrinks to a one-liner and we can
# cover the mutation semantics with pytest.
def toggle_collapsed(collapsed_set, ns_key):
    """Flip ``ns_key``'s membership in ``collapsed_set`` in place.

    A namespace that was collapsed becomes expanded (and vice versa).
    Returns the *new* visibility as a bool — ``True`` means the cards
    for this namespace should now be shown.
    """
    if ns_key in collapsed_set:
        collapsed_set.discard(ns_key)
        return True
    collapsed_set.add(ns_key)
    return False


# Centralised so both the initial header construction and the toggle
# path pick the same glyph — prevents the kind of drift that had one
# code path show ▼ while the other showed ▶ for the same state.
def arrow_glyph(visible):
    """Return the header-arrow glyph matching ``visible``.

    ``visible=True`` → ``▼`` (expanded). ``False`` → ``▶`` (collapsed).
    """
    return "\u25bc" if visible else "\u25b6"
