"""Hello Carton — a simple sample tool."""

__version__ = "1.0.0"

_window = None


def show():
    """Show the tool window."""
    global _window

    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets

    try:
        import maya.cmds as cmds
        import maya.OpenMayaUI as omui
        try:
            from shiboken6 import wrapInstance
        except ImportError:
            from shiboken2 import wrapInstance
        main_win = wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)
    except ImportError:
        cmds = None
        main_win = None

    if _window is not None:
        try:
            _window.close()
        except RuntimeError:
            pass

    _window = HelloWindow(cmds, main_win)
    _window.show()
    return _window


try:
    from PySide6 import QtWidgets as _Qw
    _BASE = _Qw.QDialog
except ImportError:
    try:
        from PySide2 import QtWidgets as _Qw
        _BASE = _Qw.QDialog
    except ImportError:
        _BASE = object


class HelloWindow(_BASE):
    """A simple window that displays scene information."""

    def __init__(self, cmds=None, parent=None):
        try:
            from PySide6 import QtWidgets as Qw, QtCore
        except ImportError:
            from PySide2 import QtWidgets as Qw, QtCore

        super().__init__(parent)
        self._cmds = cmds
        self.setWindowTitle("Hello Carton")
        self.setMinimumSize(300, 200)
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; }"
            "QLabel { color: #e0e0e0; }"
            "QPushButton {"
            "  background: #3572A5; color: white; border: none;"
            "  border-radius: 4px; padding: 8px 16px;"
            "}"
            "QPushButton:hover { background: #4682B5; }"
        )

        layout = Qw.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = Qw.QLabel("Hello Carton!")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title)

        self._info_label = Qw.QLabel("Press the button to get scene info")
        self._info_label.setStyleSheet("font-size: 13px; color: #aaa;")
        self._info_label.setAlignment(QtCore.Qt.AlignCenter)
        self._info_label.setWordWrap(True)
        layout.addWidget(self._info_label)

        layout.addStretch()

        btn = Qw.QPushButton("Get Scene Info")
        btn.clicked.connect(self._get_info)
        layout.addWidget(btn)

    def _get_info(self):
        if self._cmds is None:
            self._info_label.setText("Maya is not available (standalone mode)")
            return

        transforms = self._cmds.ls(type="transform") or []
        meshes = self._cmds.ls(type="mesh") or []
        cameras = self._cmds.ls(type="camera") or []
        scene_name = self._cmds.file(q=True, sceneName=True) or "Untitled"

        info = (
            "Scene: {}\n"
            "Transforms: {}\n"
            "Meshes: {}\n"
            "Cameras: {}"
        ).format(scene_name, len(transforms), len(meshes), len(cameras))

        self._info_label.setText(info)
