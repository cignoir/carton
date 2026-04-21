"""Shared pytest fixtures for the Carton test suite.

Provides a headless ``QApplication`` for Qt-aware tests via pytest-qt.
The ``QT_QPA_PLATFORM=offscreen`` environment variable is set before
Qt is imported so CI runs without a display server.
"""

import os

# Must be set before any PySide6 / QtWidgets import. pytest-qt consumes
# this to pick the headless platform plugin.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
