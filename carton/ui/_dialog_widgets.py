"""Shared form-row widgets for AddDialog / EditDialog.

Both dialogs render the same handful of form fields (display name, slug,
namespace + preview, icon picker, description), with differences only in
which fields appear and whether they're editable. The actual builders
live here so neither dialog has to re-implement the styling.
"""

from carton.ui.compat import QtWidgets
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
