"""Install / uninstall / launch flow for the main window.

Extracted from ``main_window.py`` so the Install + Launch state machine
sits in one file rather than competing with sidebar / publish / refresh
code for attention. The controller keeps a reference back to the
``CartonWindow`` instead of owning its own state — the window is still
the source of truth for services (downloader / install_manager /
script_manager / catalogue_client) and for the card-list widget that
install button updates need to address.
"""

import os
import traceback

from carton.core.install_state import is_my_tools
from carton.ui.compat import QtWidgets
from carton.ui.error_messages import show_error
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.package_card import PackageCard


class InstallController:
    """Handles the install / uninstall / launch button flows."""

    def __init__(self, window):
        self._w = window

    # ---- install --------------------------------------------------------

    def install(self, pkg_id, version=None, pinned=False):
        """Install a package. Optionally a specific version and/or pin it."""
        w = self._w
        if not w._downloader or not w._install_manager:
            return
        packages = w._catalogue_client.get_packages() if w._catalogue_client else {}
        pkg_data = packages.get(pkg_id)
        if not pkg_data:
            return

        self.set_install_button_state(pkg_id, busy=True)
        QtWidgets.QApplication.processEvents()

        pkg_name = pkg_data.get("name", "")
        target_version = version or pkg_data.get("latest_version", "")
        version_info = pkg_data.get("versions", {}).get(target_version, {})

        try:
            url = version_info.get("download_url")
            if not url:
                raise RuntimeError(t("no_download_url"))

            # Strict verify: refuse to install anything from a catalogue
            # entry that doesn't carry a sha256.
            if w._config and w._config.strict_verify:
                if not version_info.get("sha256"):
                    raise RuntimeError(t("install_strict_no_sha256"))

            dest = os.path.join(
                w._install_manager._config.staging_dir,
                "{}-{}.zip".format(pkg_name, target_version),
            )
            w._downloader.download(
                url, dest,
                expected_sha256=version_info.get("sha256"),
                expected_size=version_info.get("size_bytes"),
            )

            meta = {
                "id": pkg_id,
                "namespace": pkg_data.get("namespace", ""),
                "name": pkg_name,
                "version": target_version,
                "type": pkg_data.get("type", "python_package"),
                "pinned": bool(pinned),
                # Resolved absolute icon path so a relinked My Tools
                # entry can render its custom icon without re-fetching.
                "icon_resolved": w._resolve_icon_path(pkg_data) or "",
            }
            w._install_manager.install_package(dest, meta)

            if os.path.exists(dest):
                os.remove(dest)

            # Refresh sidebar too — installs that auto-relink as My
            # Tools entries change the My Tools count and namespace
            # children, and the sidebar wouldn't otherwise notice.
            w._rebuild_sidebar()
            w._rebuild_cards()

        except Exception as e:
            self.set_install_button_state(pkg_id, busy=False)
            show_error(w, e, operation="install")

    def set_install_button_state(self, pkg_id, busy=True):
        w = self._w
        for i in range(w._card_layout.count()):
            item = w._card_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, PackageCard) and widget._pkg_id == pkg_id:
                for btn in widget.findChildren(QtWidgets.QPushButton):
                    if btn.text() in (t("install"), t("installing")):
                        if busy:
                            btn.setText(t("installing"))
                            btn.setEnabled(False)
                            btn.setStyleSheet(
                                theme.btn_card_action(
                                    theme.BORDER_HOVER, theme.BORDER_HOVER,
                                    text_color=theme.TEXT_DIM)
                            )
                        else:
                            btn.setText(t("install"))
                            btn.setEnabled(True)
                            btn.setStyleSheet(
                                theme.btn_card_action(
                                    theme.ACCENT_GREEN, theme.ACCENT_GREEN_HOVER,
                                    text_color=theme.BG_PRIMARY)
                            )
                        return

    # ---- uninstall ------------------------------------------------------

    def uninstall(self, pkg_id):
        w = self._w
        packages = w._catalogue_client.get_packages() if w._catalogue_client else {}
        display = packages.get(pkg_id, {}).get("display_name", pkg_id)
        reply = QtWidgets.QMessageBox.question(
            w, t("uninstall"),
            t("confirm_uninstall", display),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            w._install_manager.uninstall_package(pkg_id)
            w._rebuild_cards()
            w._stack.setCurrentIndex(0)

    # ---- launch ---------------------------------------------------------

    def launch(self, pkg_id):
        from carton.core.entry_point_resolver import resolve_entry_point

        w = self._w
        installed = w._install_manager.get_installed_packages()
        pkg_data = installed.get(pkg_id, {})
        # Resolve entry_point: zip's inner package.json is SoT for catalogue
        # installs; installed.json carries it for My Tools only.
        package_dir = ""
        rel = pkg_data.get("path", "")
        if rel and w._install_manager:
            package_dir = os.path.join(
                w._install_manager._config.install_dir, rel,
            )
        catalogue_packages = (
            w._catalogue_client.get_packages() if w._catalogue_client else {}
        )
        entry_point = resolve_entry_point(
            pkg_data, package_dir=package_dir,
            registry_data=catalogue_packages.get(pkg_id),
        )
        # Inject the resolved entry_point back into pkg_data so handlers /
        # script_manager that read meta["entry_point"] still get a value.
        pkg_data = dict(pkg_data)
        pkg_data["entry_point"] = entry_point
        try:
            if is_my_tools(pkg_data) and w._script_manager:
                w._script_manager.launch(pkg_data)
                # Maya modules without an explicit launch command have no
                # visible feedback (userSetup.py runs deferred), so show a
                # short confirmation so the click doesn't feel broken.
                if (pkg_data.get("type") == "maya_module"
                        and not (entry_point.get("command")
                                 or entry_point.get("module"))):
                    QtWidgets.QMessageBox.information(
                        w, t("activate"), t("activate_done"),
                    )
                return
            if entry_point.get("type") == "exec" and w._script_manager:
                exec_data = dict(pkg_data)
                if not exec_data.get("local_path"):
                    # Use the relative path the installer recorded — it
                    # already accounts for the namespace ("packages/<ns>/
                    # <name>") so we don't accidentally drop it here and
                    # look for the file under "packages/<name>".
                    rel = pkg_data.get("path", "")
                    exec_file = entry_point.get("file", "")
                    if rel:
                        exec_data["local_path"] = os.path.join(
                            w._install_manager._config.install_dir,
                            rel, exec_file,
                        )
                    else:
                        exec_data["local_path"] = os.path.join(
                            w._install_manager._config.packages_dir,
                            pkg_data.get("name", ""), exec_file,
                        )
                w._script_manager.launch(exec_data)
            else:
                from carton.core.handlers import get_handler
                handler = get_handler(pkg_data.get("type", "python_package"))
                handler.launch(pkg_data)
        except Exception as e:
            self.show_launch_error(e)

    def show_launch_error(self, exc):
        """Show a launch failure with the full traceback in Show Details.

        Many "Carton launch errors" are actually exceptions from inside
        the tool the user just ran (e.g. ``NoneType object is not
        subscriptable`` from ``cmds.ls(sl=True)[0]`` with no selection).
        Surfacing the traceback makes it obvious whether to investigate
        Carton or the tool itself.
        """
        tb_text = traceback.format_exc()
        box = QtWidgets.QMessageBox(self._w)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(t("launch_error"))
        box.setText(str(exc))
        box.setInformativeText(t("launch_error_hint"))
        box.setDetailedText(tb_text)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.exec_()
