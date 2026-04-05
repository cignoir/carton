"""Shared UI utility functions."""

import os
import re

from carton.ui.compat import QtGui, Qt


def list_functions(path):
    """Return a list of all public function names in a Python file."""
    functions = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^def ([a-zA-Z][a-zA-Z0-9_]*)\s*\(", line)
                if m:
                    functions.append(m.group(1))
    except (OSError, UnicodeDecodeError):
        pass
    return functions


def resolve_icon(icon_label, icon_value, resolved_path, size=40,
                 default_icon_path=None):
    """Set icon on a QLabel from a resolved path, emoji, or default.

    Args:
        icon_label: QLabel to set the icon on.
        icon_value: Raw icon value from package data (str, bool, etc.).
        resolved_path: Pre-resolved local file path for the icon, or None.
        size: Pixel size for scaling pixmaps.
        default_icon_path: Path to fallback default icon file.
    """
    bg_style = "QLabel {{ background: transparent; border-radius: 8px; }}"

    if resolved_path and os.path.exists(resolved_path):
        pixmap = QtGui.QPixmap(resolved_path)
        icon_label.setPixmap(
            pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        icon_label.setStyleSheet(bg_style)
        return

    if (isinstance(icon_value, str) and icon_value
            and icon_value not in ("true", "false")
            and not icon_value.endswith((".png", ".jpg", ".svg"))):
        # Emoji icon
        icon_label.setText(icon_value)
        icon_label.setStyleSheet(
            "QLabel {{ background: transparent; border-radius: 8px;"
            "  font-size: {}px; }}".format(size - 16 if size > 24 else size)
        )
        return

    # Default icon
    if default_icon_path and os.path.exists(default_icon_path):
        pixmap = QtGui.QPixmap(default_icon_path)
        icon_label.setPixmap(
            pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        icon_label.setStyleSheet(bg_style)
    else:
        icon_label.setText("\U0001f4e6")
        icon_label.setStyleSheet(
            "QLabel {{ background: transparent; border-radius: 8px;"
            "  font-size: {}px; }}".format(size - 16 if size > 24 else size)
        )
