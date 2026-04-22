"""Self-update banner flow for the main window.

Drives the "new Carton release available" banner: probes GitHub on a
background thread, toggles the banner widget, and runs the staged
update on click. The worker class lives here so all three phases
(check / probe completed / user clicked update) sit next to each
other instead of being split between module scope and the main
window.
"""

from carton.ui.compat import QtCore, QtWidgets
from carton.ui.error_messages import show_error
from carton.ui.i18n import t


class SelfUpdateCheckWorker(QtCore.QThread):
    """Background worker that probes GitHub for a new Carton release.

    Emits ``finished_signal(result, error)`` where ``result`` is either
    ``None`` (no update) or ``(version, download_url)``, and ``error`` is
    a string (or ``""`` on success). Running the probe off-thread keeps
    the UI responsive when the network is slow or unreachable.
    """

    finished_signal = QtCore.Signal(object, str)

    def __init__(self, self_updater, parent=None):
        super().__init__(parent)
        self._self_updater = self_updater

    def run(self):
        try:
            result = self._self_updater.check_update()
        except Exception as e:
            self.finished_signal.emit(None, str(e))
            return
        self.finished_signal.emit(result, "")


class SelfUpdateController:
    """Drives the self-update check / apply cycle against the banner widget."""

    def __init__(self, window):
        self._w = window

    def check(self, force=False):
        """Poll GitHub for a newer Carton release and update the banner.

        Respects ``config.auto_check_updates``. Pass ``force=True`` to
        bypass the setting (used by the manual "Check now" button).

        The GitHub probe runs on a background thread so a slow or
        unreachable network never blocks the UI. The banner is updated
        from the worker's finished signal.
        """
        w = self._w
        if not w._self_updater:
            return

        # Pending staged updates are a pure local file check — do this
        # synchronously so the banner appears immediately on startup.
        if w._self_updater.has_pending_update():
            ver = w._self_updater.get_pending_version()
            w._update_banner_label.setText(t("update_pending", ver))
            w._update_banner_btn.setVisible(False)
            w._update_banner.setVisible(True)
            return

        if not force and w._config and not w._config.auto_check_updates:
            # Auto-check disabled and nothing staged — keep the banner
            # hidden and skip the network entirely.
            w._update_banner.setVisible(False)
            return

        # Don't stack multiple in-flight checks if the user mashes refresh.
        if w._update_check_worker and w._update_check_worker.isRunning():
            return

        w._update_banner.setVisible(False)
        w._update_check_worker = SelfUpdateCheckWorker(
            w._self_updater, parent=w,
        )
        w._update_check_worker.finished_signal.connect(self.on_check_done)
        w._update_check_worker.start()

    def on_check_done(self, result, error):
        """Slot for SelfUpdateCheckWorker. Runs on the UI thread."""
        w = self._w
        if error or not result:
            # Silent on failure: the banner just stays hidden. The user
            # can still click "Check for updates now" in Settings to get
            # an explicit error message.
            return
        w._pending_self_update = result  # (version, download_url)
        w._update_banner_label.setText(t("update_available", result[0]))
        w._update_banner_btn.setVisible(True)
        w._update_banner.setVisible(True)

    def apply(self):
        w = self._w
        if not getattr(w, "_pending_self_update", None):
            return
        version, download_url = w._pending_self_update
        w._update_banner_btn.setText(t("updating"))
        w._update_banner_btn.setEnabled(False)
        QtWidgets.QApplication.processEvents()
        try:
            w._self_updater.stage_update(version, download_url)
            w._update_banner_label.setText(
                t("update_pending", version)
            )
            w._update_banner_btn.setVisible(False)
            w._pending_self_update = None
        except Exception as e:
            w._update_banner_btn.setText(t("update"))
            w._update_banner_btn.setEnabled(True)
            show_error(w, e, operation="update")
