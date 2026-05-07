"""Shared form-row widgets for AddDialog / EditDialog.

Both dialogs render the same handful of form fields (display name, slug,
namespace + preview, icon picker, description), with differences only in
which fields appear and whether they're editable. The actual builders
live here so neither dialog has to re-implement the styling.
"""

from carton.ui.compat import QtCore, QtGui, QtWidgets, Qt
from carton.ui.i18n import t
from carton.ui import theme
from carton.core.identity import slugify_namespace


def make_dim_label(text, tooltip=None):
    """Form label styled with the muted dialog label color."""
    label = QtWidgets.QLabel(text)
    label.setStyleSheet(theme.LABEL_DIM)
    if tooltip:
        label.setToolTip(tooltip)
    return label


def make_readonly_input(value, tooltip=None, placeholder=None):
    """Read-only QLineEdit rendered in dim text color."""
    edit = QtWidgets.QLineEdit(value or "")
    edit.setReadOnly(True)
    edit.setStyleSheet(edit.styleSheet() + " color: {};".format(theme.TEXT_DIM))
    if tooltip:
        edit.setToolTip(tooltip)
    if placeholder:
        edit.setPlaceholderText(placeholder)
    return edit


def make_namespace_preview_label():
    """Empty, hidden label used to preview the slugified namespace."""
    label = QtWidgets.QLabel("")
    label.setStyleSheet("color: {}; font-size: 11px;".format(theme.TEXT_MUTED))
    label.setVisible(False)
    return label


def update_namespace_preview(label, text):
    """Update the namespace preview ``label`` for the given raw input ``text``.

    Shows ``→ <slug>`` only when slugification would actually change the
    user's input; otherwise hides the label.
    """
    slug = slugify_namespace(text)
    if slug and slug != text.strip().lower():
        label.setText("→ {}".format(slug))
        label.setVisible(True)
    else:
        label.setText("")
        label.setVisible(False)


def make_icon_row(initial_value, on_browse):
    """Build the ``[icon input] [Browse]`` row used by add/edit dialogs.

    Returns ``(row_layout, line_edit)`` so the caller can drop the layout
    into a form and read the input value later.
    """
    row = QtWidgets.QHBoxLayout()
    edit = QtWidgets.QLineEdit(initial_value)
    row.addWidget(edit)
    btn = QtWidgets.QPushButton(t("file"))
    btn.setFixedWidth(60)
    btn.setStyleSheet(theme.btn_small_browse())
    btn.clicked.connect(on_browse)
    row.addWidget(btn)
    return row, edit


def browse_icon_into(parent, line_edit):
    """Open the icon file picker and write the result into ``line_edit``."""
    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        parent, t("label_icon"), "",
        "Images (*.png *.jpg *.svg);;All (*)",
    )
    if path:
        line_edit.setText(path)


_DEFAULT_LOCALE = "en"


# A short, well-known list of ISO-639-1 codes used as suggestions when
# the user adds a new language. Any code accepted by the package schema
# (``^[a-z]{2}(-[A-Z]{2})?$``) goes through — this list is just a typing
# aid, not a whitelist.
_LOCALE_SUGGESTIONS = (
    "en", "ja", "zh", "ko", "fr", "de", "es", "pt", "ru", "it", "nl",
    "pl", "tr", "ar", "th", "vi", "id",
    "en-US", "en-GB", "zh-CN", "zh-TW", "pt-BR",
)


def _tab_button_style():
    """Stylesheet for a language tab in :class:`LocalizedDescriptionInput`.

    Uses Qt's ``:checked`` state so the same button can render as
    inactive (muted ghost) or active (accent fill) without us swapping
    stylesheets in code.
    """
    return (
        "QPushButton {{"
        "  background: {bg2}; color: {dim};"
        "  border: 1px solid {border}; border-radius: 3px;"
        "  padding: 2px 8px; font-size: 11px; min-width: 28px;"
        "  font-weight: 600; text-transform: uppercase;"
        "}}"
        "QPushButton:hover {{"
        "  background: {hover}; color: {text};"
        "  border-color: {border_hover};"
        "}}"
        "QPushButton:checked {{"
        "  background: {accent}; color: white; border-color: {accent};"
        "}}"
    ).format(
        bg2=theme.BG_SECONDARY, dim=theme.TEXT_DIM, text=theme.TEXT_PRIMARY,
        hover=theme.BG_HOVER, border=theme.BORDER,
        border_hover=theme.BORDER_HOVER, accent=theme.ACCENT_BLUE,
    )


class LocalizedDescriptionInput(QtWidgets.QWidget):
    """Compact one-row description input with a language tab switcher.

    Pairs with :func:`carton.ui.i18n.resolve_localized`. The manifest
    ``description`` field can be a single string (one language,
    all-purpose) or a dict keyed by ISO-639-1 codes such as ``en`` /
    ``ja`` / ``fr`` / ``zh-TW``. This widget round-trips both forms.

    Visual layout
    -------------
    ::

        [EN] [JA] [FR] [+]                 ← tab row
        [text input for the active tab]    ← single line, swaps on click

    * Click a tab → the input swaps to show that language's text.
    * Right-click a tab → context menu with ``Remove``.
    * ``+`` → mini prompt for a new locale code.

    Round-trip rules (same as before)
    ---------------------------------
    * Load string ``"foo"`` → one tab with locale ``"en"`` (the
      conventional default), text ``"foo"``.
    * Load dict — one tab per key in iteration order.
    * Save with no non-empty entries → empty string.
    * Save with exactly the default-locale entry → collapse to plain
      string for backward compatibility.
    * Save with anything else → dict ``{locale: text}``. Empty values
      are dropped.
    """

    # Pin enough vertical room for the tab strip + text input. Without
    # these explicit heights, QFormLayout sometimes squishes a composite
    # widget down to a few pixels because its layout-derived sizeHint
    # doesn't propagate the way a plain QLineEdit's does.
    _TAB_ROW_HEIGHT = 22
    _INPUT_MIN_HEIGHT = 28
    _OUTER_SPACING = 4

    def __init__(self, parent=None, default_locale=_DEFAULT_LOCALE):
        super().__init__(parent)
        self._default_locale = default_locale
        # Keep insertion order so the tab row reflects manifest order.
        # ``_strings`` always carries every locale the user has touched,
        # including empty entries — the empty-filter only happens at
        # ``get_value`` time so the user can clear and refill without
        # losing the tab.
        self._strings: dict[str, str] = {}
        self._active: str = default_locale
        self._tab_buttons: dict[str, QtWidgets.QPushButton] = {}

        # Vertical Fixed so neighbouring form rows can't steal our height.
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Fixed,
        )
        self.setMinimumHeight(
            self._TAB_ROW_HEIGHT + self._OUTER_SPACING + self._INPUT_MIN_HEIGHT
        )

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(self._OUTER_SPACING)

        # ── Tab row ──
        tab_row_widget = QtWidgets.QWidget(self)
        tab_row_widget.setFixedHeight(self._TAB_ROW_HEIGHT)
        self._tab_row = QtWidgets.QHBoxLayout(tab_row_widget)
        self._tab_row.setContentsMargins(0, 0, 0, 0)
        self._tab_row.setSpacing(2)
        outer.addWidget(tab_row_widget)

        # ── Text input (shared, swaps content on tab click) ──
        self._text_input = QtWidgets.QLineEdit(self)
        self._text_input.setMinimumHeight(self._INPUT_MIN_HEIGHT)
        self._text_input.textChanged.connect(self._on_text_changed)
        outer.addWidget(self._text_input)

        # ``+`` button is created once and re-parented at the end of the
        # tab row on every rebuild so it stays after the language tabs.
        self._add_btn = QtWidgets.QPushButton("+", self)
        self._add_btn.setFixedSize(28, 22)
        self._add_btn.setStyleSheet(theme.btn_small_browse())
        self._add_btn.setToolTip(t("desc_add_locale_tooltip"))
        self._add_btn.clicked.connect(self._on_add_clicked)

        # Start with a single empty default-locale tab so the widget is
        # immediately usable on a fresh dialog.
        self._strings[self._default_locale] = ""
        self._active = self._default_locale
        self._rebuild_tabs()
        self._show_active()

    # ------------------------------------------------------------------
    # Tab rendering
    # ------------------------------------------------------------------

    def _rebuild_tabs(self) -> None:
        """Wipe the tab row and re-add a button per known locale + the
        ``+`` add button. Called after ``_strings`` mutates."""
        # Clear (deleteLater on each child widget so Qt destroys them
        # cleanly without leaving zombies).
        while self._tab_row.count():
            item = self._tab_row.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._add_btn:
                w.setParent(None)
                w.deleteLater()

        self._tab_buttons = {}
        for code in self._strings:
            btn = self._make_tab_button(code)
            self._tab_buttons[code] = btn
            self._tab_row.addWidget(btn)

        self._tab_row.addWidget(self._add_btn)
        self._tab_row.addStretch(1)

    def _make_tab_button(self, code: str) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(code, self)
        btn.setCheckable(True)
        btn.setChecked(code == self._active)
        btn.setFixedHeight(22)
        btn.setStyleSheet(_tab_button_style())
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setToolTip(
            "{}\n{}".format(code, t("desc_remove_locale_tooltip"))
        )
        btn.clicked.connect(lambda _checked=False, c=code: self._on_tab_clicked(c))
        # Right-click → remove. CustomContextMenu lets us catch the
        # gesture without subclassing.
        btn.setContextMenuPolicy(Qt.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda _pos, c=code, b=btn: self._on_tab_context(c, b)
        )
        return btn

    # ------------------------------------------------------------------
    # State syncing between the text input and ``_strings``
    # ------------------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        """Mirror the input contents into the active locale's slot on
        every keystroke so a tab switch never loses unsaved typing."""
        if self._active:
            self._strings[self._active] = text

    def _show_active(self) -> None:
        """Replace the input contents with the active locale's text.
        Blocks signals so we don't echo back into ``_on_text_changed``
        and dirty the slot we just loaded from."""
        self._text_input.blockSignals(True)
        try:
            self._text_input.setText(self._strings.get(self._active, ""))
        finally:
            self._text_input.blockSignals(False)
        self._text_input.setPlaceholderText(
            "{} ({})".format(t("label_description"), self._active)
        )

    # ------------------------------------------------------------------
    # Tab actions
    # ------------------------------------------------------------------

    def _on_tab_clicked(self, code: str) -> None:
        if code == self._active:
            # Re-checking the active tab shouldn't toggle it off — keep
            # one tab always selected.
            self._tab_buttons[code].setChecked(True)
            return
        self._active = code
        for c, btn in self._tab_buttons.items():
            btn.setChecked(c == code)
        self._show_active()

    def _on_tab_context(self, code: str, button) -> None:
        menu = QtWidgets.QMenu(self)
        remove_action = menu.addAction(t("desc_remove_locale_tooltip"))
        if menu.exec_(QtGui.QCursor.pos()) is remove_action:
            self._remove_locale(code)

    def _remove_locale(self, code: str) -> None:
        if code not in self._strings:
            return
        # Keep at least one tab around — never let the widget end up
        # with zero tabs and a stale active locale.
        if len(self._strings) == 1:
            # Just clear the single tab's text instead of removing it.
            self._strings[code] = ""
            self._show_active()
            return
        del self._strings[code]
        if self._active == code:
            self._active = next(iter(self._strings))
        self._rebuild_tabs()
        self._show_active()

    def _on_add_clicked(self) -> None:
        suggestion = self._suggest_new_locale()
        code, ok = QtWidgets.QInputDialog.getText(
            self,
            t("desc_add_locale"),
            t("desc_add_locale_prompt"),
            QtWidgets.QLineEdit.Normal,
            suggestion,
        )
        if not ok:
            return
        normalized = code.strip().lower()
        if not normalized:
            return
        # Switching to an existing locale is a soft success — pick its
        # tab instead of creating a duplicate.
        if normalized not in self._strings:
            self._strings[normalized] = ""
        self._active = normalized
        self._rebuild_tabs()
        self._show_active()

    def _suggest_new_locale(self) -> str:
        """Best guess for the locale code to pre-fill in the add prompt.

        Order: live Carton UI language → default locale → first unused
        suggestion → empty string. The user can overwrite anything.
        """
        used = set(self._strings.keys())
        for code in (self._active_locale_hint(), self._default_locale):
            if code and code not in used:
                return code
        for code in _LOCALE_SUGGESTIONS:
            if code not in used:
                return code
        return ""

    def _active_locale_hint(self) -> str:
        try:
            from carton.ui.i18n import get_language
            return get_language() or ""
        except ImportError:
            return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_value(self, value) -> None:
        """Populate from a manifest value (string, dict, or empty)."""
        self._strings = {}
        if isinstance(value, str):
            seed_locale = self._default_locale
            self._strings[seed_locale] = value
        elif isinstance(value, dict):
            for k, v in value.items():
                if isinstance(k, str) and isinstance(v, str):
                    self._strings[k] = v
            if not self._strings:
                self._strings[self._default_locale] = ""
        else:
            # Anything malformed (None, ints, lists, ...) → start blank.
            self._strings[self._default_locale] = ""

        # Pick a sensible starting tab. Default locale wins if present
        # so loaded strings show "as the user authored them"; otherwise
        # the first key the manifest carried.
        if self._default_locale in self._strings:
            self._active = self._default_locale
        else:
            self._active = next(iter(self._strings))

        self._rebuild_tabs()
        self._show_active()

    def get_value(self):
        """Return the manifest-shape value (string, dict or '')."""
        # Make sure the in-memory store reflects the input's current
        # contents — the user may have stopped typing without giving up
        # focus, so textChanged has fired but we want freshness anyway.
        if self._active:
            self._strings[self._active] = self._text_input.text()

        kept = {
            k: v.strip() for k, v in self._strings.items()
            if isinstance(v, str) and v.strip()
        }
        if not kept:
            return ""
        if list(kept.keys()) == [self._default_locale]:
            return kept[self._default_locale]
        return kept
