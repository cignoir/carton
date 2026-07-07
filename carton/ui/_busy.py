"""Run a blocking callable off the UI thread behind a busy dialog.

The Settings catalogue-add flows hit the network from button slots;
running them inline freezes all of Maya on a slow connection. This
helper keeps the calling code shaped like a plain function call —
``result = run_with_busy(parent, fn)`` — while the work happens on a
QThread and the UI stays responsive behind a modal indeterminate
progress dialog.

Exceptions raised by ``fn`` are re-raised in the calling thread with
their original type, so existing ``try/except CatalogueSourceError``
blocks keep working unchanged.
"""

from carton.ui.compat import QtCore, QtWidgets, Qt
from carton.ui.i18n import t


class _FnWorker(QtCore.QThread):
    # (result, exception) — exactly one of the two is None.
    finished_signal = QtCore.Signal(object, object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as e:
            self.finished_signal.emit(None, e)
            return
        self.finished_signal.emit(result, None)


def run_with_busy(parent, fn, label="", show_after_ms=300):
    """Execute ``fn()`` on a worker thread; return its result or re-raise.

    Blocks the caller (a local event loop runs meanwhile, so the UI
    keeps painting and Maya doesn't white-screen). The busy dialog only
    appears when the call takes longer than ``show_after_ms`` — fast
    calls finish without a flash of UI.
    """
    dialog = QtWidgets.QProgressDialog(
        label or t("busy_network"), "", 0, 0, parent,
    )
    dialog.setWindowTitle("Carton")
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setCancelButton(None)
    dialog.setMinimumDuration(2 ** 31 - 1)  # we control visibility ourselves

    state = {}
    loop = QtCore.QEventLoop()

    def _done(result, error):
        state["result"] = result
        state["error"] = error
        loop.quit()

    worker = _FnWorker(fn, parent=parent)
    worker.finished_signal.connect(_done)

    show_timer = QtCore.QTimer(parent)
    show_timer.setSingleShot(True)
    show_timer.timeout.connect(dialog.show)
    show_timer.start(show_after_ms)

    worker.start()
    # The finished signal crosses threads, so it is queued — it can only
    # be delivered inside this event loop, never before exec starts.
    # PySide6 deprecates exec_() on QEventLoop; PySide2 lacks exec.
    if hasattr(loop, "exec"):
        loop.exec()
    else:
        loop.exec_()
    worker.wait(5000)

    show_timer.stop()
    dialog.close()
    dialog.deleteLater()

    if state.get("error") is not None:
        raise state["error"]
    return state.get("result")
