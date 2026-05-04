"""Shared form-row widgets for AddDialog / EditDialog.

Both dialogs render the same handful of form fields (display name, slug,
namespace + preview, icon picker, description), with differences only in
which fields appear and whether they're editable. The actual builders
live here so neither dialog has to re-implement the styling.
"""

from carton.ui.compat import QtCore, QtWidgets, Qt
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


# A short, well-known list of ISO-639-1 codes used as completer
# suggestions when the user types a locale code. Any code that matches
# the schema's pattern (^[a-z]{2}(-[A-Z]{2})?$) is accepted regardless of
# whether it appears here — this is purely a typing aid, not a whitelist.
_LOCALE_SUGGESTIONS = (
    "en", "ja", "zh", "ko", "fr", "de", "es", "pt", "ru", "it", "nl",
    "pl", "tr", "ar", "th", "vi", "id",
    "en-US", "en-GB", "zh-CN", "zh-TW", "pt-BR",
)


def _locale_completer(parent):
    """Build a QCompleter populated with the suggestion list."""
    completer = QtWidgets.QCompleter(list(_LOCALE_SUGGESTIONS), parent)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchStartsWith)
    return completer


class _LocaleRow(QtWidgets.QWidget):
    """One ``[locale code] [text] [×]`` row inside the description widget."""

    removed = None  # set in __init__ once the parent connects

    def __init__(self, locale="", text="", parent=None):
        super().__init__(parent)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.locale_input = QtWidgets.QLineEdit(locale)
        self.locale_input.setFixedWidth(64)
        self.locale_input.setMaxLength(8)
        self.locale_input.setPlaceholderText("en")
        self.locale_input.setToolTip(
            "ISO-639-1 language code (e.g. en, ja, zh, fr) "
            "with optional region (e.g. en-US, pt-BR)."
        )
        self.locale_input.setCompleter(_locale_completer(self))

        self.text_input = QtWidgets.QLineEdit(text)

        self.remove_btn = QtWidgets.QPushButton("×")
        self.remove_btn.setFixedWidth(24)
        self.remove_btn.setStyleSheet(theme.btn_small_browse())
        self.remove_btn.setToolTip(t("desc_remove_locale_tooltip"))

        layout.addWidget(self.locale_input)
        layout.addWidget(self.text_input, 1)
        layout.addWidget(self.remove_btn)


class LocalizedDescriptionInput(QtWidgets.QWidget):
    """Variable-length list of ``(locale, text)`` rows.

    Pairs with :func:`carton.ui.i18n.resolve_localized`. The manifest
    ``description`` field can be a single string (one language,
    all-purpose) or a dict keyed by ISO-639-1 codes such as ``en`` /
    ``ja`` / ``fr`` / ``zh-TW``. This widget round-trips both forms
    without the en/ja hardcoding the original draft had — any locale
    code accepted by the package schema is editable here.

    Round-trip rules
    ----------------
    * Load string ``"foo"`` → one row with locale ``"en"`` (the
      conventional default), text ``"foo"``.
    * Load dict — one row per key in iteration order.
    * Save with no rows → empty string.
    * Save with exactly one row whose locale is the default ``"en"`` →
      collapse to a plain string for backward compatibility with
      single-language manifests.
    * Save with everything else → dict ``{locale: text}``. Empty rows
      and rows with empty locale codes are dropped.

    Locale codes the user types are passed through verbatim as long as
    they're non-empty; the package schema is the validation gate. The
    completer suggests common ISO codes but doesn't restrict input.
    """

    def __init__(self, parent=None, default_locale=_DEFAULT_LOCALE):
        super().__init__(parent)
        self._default_locale = default_locale
        self._rows = []  # list[_LocaleRow]

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._rows_container = QtWidgets.QWidget(self)
        self._rows_layout = QtWidgets.QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        outer.addWidget(self._rows_container)

        self._add_btn = QtWidgets.QPushButton(t("desc_add_locale"))
        self._add_btn.setStyleSheet(theme.btn_small_browse())
        self._add_btn.setToolTip(t("desc_add_locale_tooltip"))
        self._add_btn.clicked.connect(self._on_add_clicked)
        # Left-align the button by wrapping it in a row that stretches.
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addWidget(self._add_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def _add_row(self, locale="", text=""):
        row = _LocaleRow(locale=locale, text=text, parent=self._rows_container)
        row.remove_btn.clicked.connect(lambda _=None, r=row: self._remove_row(r))
        self._rows_layout.addWidget(row)
        self._rows.append(row)
        return row

    def _remove_row(self, row):
        if row not in self._rows:
            return
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()

    def _clear_rows(self):
        for row in list(self._rows):
            self._rows.remove(row)
            self._rows_layout.removeWidget(row)
            row.deleteLater()

    def _on_add_clicked(self):
        # Pick a locale that isn't already used as the suggested code.
        used = {r.locale_input.text().strip() for r in self._rows}
        suggestion = ""
        for code in (self._active_locale_hint(), self._default_locale):
            if code and code not in used:
                suggestion = code
                break
        if not suggestion:
            for code in _LOCALE_SUGGESTIONS:
                if code not in used:
                    suggestion = code
                    break
        self._add_row(locale=suggestion)

    def _active_locale_hint(self):
        """Return the live Carton UI language so a new row defaults to
        something useful — usually whatever the user is staring at."""
        try:
            from carton.ui.i18n import get_language
            return get_language() or ""
        except ImportError:
            return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_value(self, value):
        """Populate rows from a manifest value (string, dict, or empty)."""
        self._clear_rows()
        if isinstance(value, str):
            if value:
                self._add_row(locale=self._default_locale, text=value)
            else:
                # Start with a single empty row pre-tagged with the
                # active UI locale so the user has somewhere to type.
                self._add_row(
                    locale=self._active_locale_hint() or self._default_locale,
                )
            return
        if isinstance(value, dict):
            for k, v in value.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                self._add_row(locale=k, text=v)
            if not self._rows:
                self._add_row(
                    locale=self._active_locale_hint() or self._default_locale,
                )
            return
        # Anything else (None, ints, lists, ...) → start blank.
        self._add_row(
            locale=self._active_locale_hint() or self._default_locale,
        )

    def get_value(self):
        """Return the manifest-shape value (string, dict or '')."""
        kept = {}
        for row in self._rows:
            code = row.locale_input.text().strip()
            text = row.text_input.text().strip()
            if not code or not text:
                continue
            kept[code] = text

        if not kept:
            return ""
        # Single default-locale entry collapses to plain string for
        # backward compat with manifests authored before localization.
        if list(kept.keys()) == [self._default_locale]:
            return kept[self._default_locale]
        return kept
