"""PySide2 / PySide6 compatibility layer."""

try:
    from PySide6 import QtWidgets, QtCore, QtGui
    from PySide6.QtCore import Qt, Signal, Slot
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Qt, Signal, Slot
    from shiboken2 import wrapInstance

__all__ = ["QtWidgets", "QtCore", "QtGui", "Qt", "Signal", "Slot", "wrapInstance"]
