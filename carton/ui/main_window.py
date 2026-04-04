"""Carton main window."""

import json
import os
from collections import OrderedDict

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, Request, URLError

try:
    from urllib.parse import urljoin
except ImportError:
    from urlparse import urljoin

from carton.ui.compat import QtWidgets, QtCore, Qt, wrapInstance
from carton.ui.i18n import t
from carton.ui.package_card import PackageCard
from carton.ui.package_detail import PackageDetailPanel
from carton.ui.settings_dialog import SettingsDialog
from carton.ui.add_dialog import AddDialog
from carton.ui.edit_dialog import EditDialog

_WINDOW_TITLE = "Carton"
_WINDOW_WIDTH = 480
_WINDOW_HEIGHT = 600


class _RegistryGroup(QtWidgets.QWidget):
    """Registry group header. Click to collapse/expand."""

    def __init__(self, registry_name, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._cards = []

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)

        self._arrow = QtWidgets.QLabel("▼")
        self._arrow.setFixedWidth(16)
        self._arrow.setStyleSheet("color: #555; font-size: 10px; background: transparent;")
        layout.addWidget(self._arrow)

        label = QtWidgets.QLabel(registry_name.upper())
        label.setStyleSheet(
            "color: #6e6e6e; font-size: 11px; font-weight: 600;"
            " letter-spacing: 1px; background: transparent;"
        )
        layout.addWidget(label)

        layout.addStretch()
        self.setCursor(Qt.PointingHandCursor)

    def add_card(self, card):
        self._cards.append(card)

    def mousePressEvent(self, event):
        self._collapsed = not self._collapsed
        self._arrow.setText("▶" if self._collapsed else "▼")
        for card in self._cards:
            card.setVisible(not self._collapsed)


_STYLE = """
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Segoe UI", "Yu Gothic UI", sans-serif;
}
QLineEdit {
    background: #252526;
    border: 1px solid #333;
    border-radius: 6px;
    padding: 7px 12px;
    color: #e0e0e0;
    font-size: 13px;
    selection-background-color: #264f78;
}
QLineEdit:focus {
    border-color: #3572A5;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #3a3a3a;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #555;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
"""


class CartonWindow(QtWidgets.QDialog):
    """Carton package manager main window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        import carton
        self.setWindowTitle("{} v{}".format(_WINDOW_TITLE, carton.__version__))
        self.setMinimumSize(_WINDOW_WIDTH, _WINDOW_HEIGHT)
        self.setStyleSheet(_STYLE)

        self._registry_client = None
        self._install_manager = None
        self._downloader = None
        self._self_updater = None
        self._script_manager = None
        self._publisher = None
        self._config = None

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._stack = QtWidgets.QStackedWidget()
        main_layout.addWidget(self._stack)

        # ---- Page 0: Package list ----
        list_page = QtWidgets.QWidget()
        list_layout = QtWidgets.QVBoxLayout(list_page)
        list_layout.setContentsMargins(16, 16, 16, 16)
        list_layout.setSpacing(12)

        # Update banner
        self._update_banner = QtWidgets.QWidget()
        self._update_banner.setFixedHeight(32)
        self._update_banner.setStyleSheet(
            "QWidget { background: #2a2517; border: 1px solid #3e3520; border-radius: 6px; }"
        )
        self._update_banner.setVisible(False)
        banner_layout = QtWidgets.QHBoxLayout(self._update_banner)
        banner_layout.setContentsMargins(10, 0, 6, 0)
        banner_layout.setSpacing(8)
        self._update_banner_label = QtWidgets.QLabel()
        self._update_banner_label.setStyleSheet(
            "color: #FFB74D; font-size: 11px; background: transparent;"
        )
        banner_layout.addWidget(self._update_banner_label)
        banner_layout.addStretch()
        self._update_banner_btn = QtWidgets.QPushButton(t("update"))
        self._update_banner_btn.setFixedHeight(20)
        self._update_banner_btn.setStyleSheet(
            "QPushButton { background: #FF9800; color: white; border: none;"
            "  border-radius: 3px; padding: 0 10px; font-size: 11px; }"
            "QPushButton:hover { background: #FFA826; }"
        )
        self._update_banner_btn.clicked.connect(self._on_self_update)
        self._update_banner_btn.setVisible(False)
        banner_layout.addWidget(self._update_banner_btn)
        list_layout.addWidget(self._update_banner)

        # Search + buttons
        search_row = QtWidgets.QHBoxLayout()
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText(t("search_placeholder"))
        self._search.textChanged.connect(self._filter_cards)
        search_row.addWidget(self._search)

        refresh_btn = QtWidgets.QPushButton("↻")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #333;"
            "  border-radius: 6px; font-size: 16px; color: #777; }"
            "QPushButton:hover { background: #2a2a2a; color: #e0e0e0; border-color: #444; }"
        )
        refresh_btn.clicked.connect(self.refresh)
        search_row.addWidget(refresh_btn)

        settings_btn = QtWidgets.QPushButton("⚙")
        settings_btn.setFixedSize(28, 28)
        settings_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #333;"
            "  border-radius: 6px; font-size: 16px; color: #777; }"
            "QPushButton:hover { background: #2a2a2a; color: #e0e0e0; border-color: #444; }"
        )
        settings_btn.clicked.connect(self._open_settings)
        search_row.addWidget(settings_btn)

        list_layout.addLayout(search_row)

        # Tabs
        tab_layout = QtWidgets.QHBoxLayout()
        self._tab_all = QtWidgets.QPushButton(t("tab_all"))
        self._tab_installed = QtWidgets.QPushButton(t("tab_installed"))
        for btn in (self._tab_all, self._tab_installed):
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                "  color: #666; font-size: 12px; padding: 0 12px; }"
                "QPushButton:hover { color: #a0a0a0; }"
                "QPushButton:checked { color: #e0e0e0; border-bottom: 2px solid #3572A5; }"
            )
        self._tab_all.setChecked(True)
        self._tab_all.clicked.connect(lambda: self._set_tab("all"))
        self._tab_installed.clicked.connect(lambda: self._set_tab("installed"))
        tab_layout.addWidget(self._tab_all)
        tab_layout.addWidget(self._tab_installed)
        tab_layout.addStretch()

        add_btn = QtWidgets.QPushButton(t("add"))
        add_btn.setFixedHeight(28)
        add_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #333;"
            "  border-radius: 6px; color: #777; font-size: 12px; padding: 0 10px; }"
            "QPushButton:hover { background: #2a2a2a; color: #e0e0e0; border-color: #444; }"
        )
        add_btn.clicked.connect(self._on_add_script)
        tab_layout.addWidget(add_btn)

        list_layout.addLayout(tab_layout)

        # Card list
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._card_container = QtWidgets.QWidget()
        self._card_layout = QtWidgets.QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(8)

        self._loading_label = QtWidgets.QLabel(t("loading"))
        self._loading_label.setStyleSheet("color: #666; font-size: 13px; background: transparent;")
        self._loading_label.setAlignment(Qt.AlignCenter)
        self._card_layout.addWidget(self._loading_label)
        self._card_layout.addStretch()

        scroll.setWidget(self._card_container)
        list_layout.addWidget(scroll)

        self._stack.addWidget(list_page)

        # ---- Page 1: Detail ----
        self._detail = PackageDetailPanel()
        self._detail.back_requested.connect(lambda: self._stack.setCurrentIndex(0))
        self._detail.install_requested.connect(self._on_install)
        self._detail.uninstall_requested.connect(self._on_uninstall)
        self._detail.launch_requested.connect(self._on_launch)
        self._stack.addWidget(self._detail)

        self._current_tab = "all"

    # ---- public API ----

    def deferred_init(self):
        QtCore.QTimer.singleShot(0, self._do_deferred_init)

    def _do_deferred_init(self):
        if self._config and not self._config.registries:
            self._prompt_registry_setup()
        self.refresh()
        self._loading_label.setVisible(False)

    def _prompt_registry_setup(self):
        """Show a setup dialog when no registries are configured."""
        reply = QtWidgets.QMessageBox.question(
            self, t("setup_title"),
            t("setup_no_registry"),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self._create_new_registry()
        else:
            QtWidgets.QMessageBox.information(
                self, "Carton",
                t("setup_no_registry_hint"),
            )

    def _create_new_registry(self):
        """Create a new empty registry directory."""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, t("setup_select_folder"),
        )
        if not folder:
            return

        name, ok = QtWidgets.QInputDialog.getText(
            self, "Registry Name",
            t("setup_registry_name"),
            text=os.path.basename(folder),
        )
        if not ok or not name:
            return

        import json
        reg_path = os.path.join(folder, "registry.json")
        if not os.path.exists(reg_path):
            os.makedirs(folder, exist_ok=True)
            with open(reg_path, "w", encoding="utf-8") as f:
                json.dump({"schema_version": "2.0", "packages": {}}, f, indent=2)
            os.makedirs(os.path.join(folder, "packages"), exist_ok=True)

        self._config.add_registry(name, reg_path)
        self._config.save()

    def set_services(self, registry_client, install_manager, downloader,
                     self_updater=None, config=None, script_manager=None,
                     publisher=None):
        self._registry_client = registry_client
        self._install_manager = install_manager
        self._downloader = downloader
        self._self_updater = self_updater
        self._script_manager = script_manager
        self._publisher = publisher
        self._config = config

    def refresh(self):
        if not self._registry_client:
            return
        self._registry_client.fetch()
        self._rebuild_cards()
        self._check_self_update()

    # ---- internal ----

    def _fetch_remote_icon(self, base_url, pkg_name):
        """Download a remote icon and cache locally. Returns local path or None."""
        if not self._config:
            return None
        cache_dir = os.path.join(self._config.install_dir, ".icon_cache")
        cached = os.path.join(cache_dir, "{}.png".format(pkg_name))
        if os.path.exists(cached):
            return cached

        icon_url = urljoin(base_url, "icons/{}.png".format(pkg_name))
        try:
            req = Request(icon_url)
            resp = urlopen(req, timeout=5)
            data = resp.read()
            os.makedirs(cache_dir, exist_ok=True)
            with open(cached, "wb") as f:
                f.write(data)
            return cached
        except Exception:
            return None

    def _rebuild_cards(self):
        """Rebuild the card list. Grouped by registry."""
        while self._card_layout.count() > 1:
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        packages = self._registry_client.get_packages() if self._registry_client else {}
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}

        all_items = {}

        for pkg_id, pkg_data in packages.items():
            item = dict(pkg_data)
            if pkg_id in installed:
                item["_installed_ver"] = installed[pkg_id].get("version")
                inst = installed[pkg_id]
                if inst.get("source") in ("local_script", "published") and inst.get("local_path"):
                    item["_local_script"] = True
            all_items[pkg_id] = item

        for pkg_id, pkg_data in installed.items():
            source = pkg_data.get("source", "")
            if source in ("local_script", "published") and pkg_id not in all_items:
                has_local_file = bool(pkg_data.get("local_path"))
                all_items[pkg_id] = {
                    "name": pkg_data.get("name", ""),
                    "display_name": pkg_data.get("display_name", ""),
                    "type": pkg_data.get("type", "python_package"),
                    "icon": pkg_data.get("icon", "📄"),
                    "description": pkg_data.get("description", ""),
                    "author": pkg_data.get("author", ""),
                    "tags": [],
                    "latest_version": pkg_data.get("version", "0.0.0"),
                    "_installed_ver": pkg_data.get("version", "0.0.0"),
                    "_local_script": has_local_file,
                    "_registry_name": "Local",
                }

        # Registry grouping
        groups = OrderedDict()
        for pkg_id, pkg_data in sorted(all_items.items(), key=lambda x: x[1].get("display_name", "")):
            is_installed = pkg_id in installed
            if self._current_tab == "installed" and not is_installed:
                continue
            reg_name = pkg_data.get("_registry_name", "Local")
            if reg_name not in groups:
                groups[reg_name] = []
            groups[reg_name].append((pkg_id, pkg_data))

        for reg_name, items in groups.items():
            group_header = _RegistryGroup(reg_name)
            idx = self._card_layout.count() - 1
            self._card_layout.insertWidget(idx, group_header)

            for pkg_id, pkg_data in items:
                installed_ver = pkg_data.get("_installed_ver")
                pkg_name = pkg_data.get("name", "")

                # Icon: from registry's icons/ (local or remote)
                icon_path = None
                icon_value = pkg_data.get("icon", "")
                if isinstance(icon_value, bool) and icon_value:
                    base_dir = pkg_data.get("_registry_base_dir", "")
                    is_remote = pkg_data.get("_registry_remote", False)
                    if base_dir:
                        if is_remote:
                            icon_path = self._fetch_remote_icon(
                                base_dir, pkg_name,
                            )
                        else:
                            candidate = os.path.join(base_dir, "icons", "{}.png".format(pkg_name))
                            if os.path.exists(candidate):
                                icon_path = candidate

                card = PackageCard(pkg_id, pkg_data, installed_version=installed_ver, icon_path=icon_path)
                card.launch_requested.connect(self._on_launch)
                card.install_requested.connect(self._on_install)
                card.publish_requested.connect(self._on_publish)
                card.update_requested.connect(self._on_update)
                card.setCursor(Qt.PointingHandCursor)

                is_local = pkg_data.get("_local_script", False)
                is_published_local = (pkg_id in installed and
                                      installed[pkg_id].get("source") in ("local_script", "published"))
                if is_local or is_published_local:
                    card.mousePressEvent = lambda e, pid=pkg_id: self._show_edit(pid)
                else:
                    card.mousePressEvent = lambda e, pid=pkg_id: self._show_detail(pid)

                group_header.add_card(card)
                idx = self._card_layout.count() - 1
                self._card_layout.insertWidget(idx, card)

    def _show_detail(self, pkg_id):
        packages = self._registry_client.get_packages() if self._registry_client else {}
        pkg_data = packages.get(pkg_id, {})
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}
        installed_ver = installed.get(pkg_id, {}).get("version")
        self._detail.show_package(pkg_id, pkg_data, installed_version=installed_ver)
        self._stack.setCurrentIndex(1)

    def _show_edit(self, pkg_id):
        installed = self._install_manager.get_installed_packages()
        pkg_data = installed.get(pkg_id, {})
        if not pkg_data:
            return

        # Check which registries have this package published
        published_regs = []
        if self._publisher:
            published_regs = self._publisher.find_published_registries(pkg_id)

        result = EditDialog.prompt(pkg_id, pkg_data,
                                   published_registries=published_regs, parent=self)
        if not result:
            return
        if result["action"] == "unpublish":
            self._on_unpublish(pkg_id, result["registry"])
            return
        if result["action"] == "remove":
            if self._script_manager:
                self._script_manager.unregister(pkg_id)
            self._rebuild_cards()
        elif result["action"] == "save":
            pkg_data["display_name"] = result["display_name"]
            pkg_data["version"] = result["version"]
            pkg_data["author"] = result["author"]
            pkg_data["icon"] = result["icon"]
            pkg_data["description"] = result["description"]
            pkg_data["entry_point"] = result["entry_point"]
            self._install_manager._installed["packages"][pkg_id] = pkg_data
            self._install_manager._save_installed()
            self._rebuild_cards()

    def _filter_cards(self, text):
        text = text.lower()
        for i in range(self._card_layout.count()):
            item = self._card_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, PackageCard):
                name = widget._pkg_data.get("name", "").lower()
                display = widget._pkg_data.get("display_name", "").lower()
                tags = " ".join(widget._pkg_data.get("tags", [])).lower()
                visible = not text or text in name or text in display or text in tags
                widget.setVisible(visible)
            elif isinstance(widget, _RegistryGroup):
                if not text:
                    widget.setVisible(True)
                else:
                    has_visible = any(
                        text in c._pkg_data.get("name", "").lower()
                        or text in c._pkg_data.get("display_name", "").lower()
                        or text in " ".join(c._pkg_data.get("tags", [])).lower()
                        for c in widget._cards
                    )
                    widget.setVisible(has_visible)

    def _set_tab(self, tab):
        self._current_tab = tab
        self._tab_all.setChecked(tab == "all")
        self._tab_installed.setChecked(tab == "installed")
        self._rebuild_cards()

    def _open_settings(self):
        if not self._config:
            return
        dialog = SettingsDialog(self._config, self)
        dialog.exec_()
        # Refresh since registries may have changed
        self.refresh()

    def _on_add_script(self):
        if not self._script_manager:
            return
        result = AddDialog.prompt(self)
        if not result:
            return
        try:
            self._script_manager.register(
                file_path=result["file_path"],
                name=result["name"],
                display_name=result["display_name"],
                icon=result["icon"],
                description=result["description"],
                pkg_type=result["type"],
                entry_point=result["entry_point"],
                is_folder=result.get("is_folder", False),
                version=result.get("version", "0.0.0"),
                author=result.get("author", ""),
                pkg_id=result.get("id"),
            )
            self._rebuild_cards()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, t("register_error"), str(e))

    def _on_publish(self, pkg_id):
        if not self._publisher or not self._config:
            return

        installed = self._install_manager.get_installed_packages()
        pkg_data = installed.get(pkg_id)
        if not pkg_data:
            return

        display = pkg_data.get("display_name", pkg_id)
        local_version = pkg_data.get("version", "0.0.0")

        # Select target registry for publishing (local only)
        registries = [r for r in self._config.registries if not r.is_remote]
        if not registries:
            QtWidgets.QMessageBox.warning(
                self, t("publish"), t("publish_no_registry"),
            )
            return

        if len(registries) == 1:
            target_registry = registries[0]
        else:
            names = [r.name for r in registries]
            chosen, ok = QtWidgets.QInputDialog.getItem(
                self, t("publish"), t("publish_select_registry"), names, 0, False,
            )
            if not ok:
                return
            target_registry = next(r for r in registries if r.name == chosen)

        reply = QtWidgets.QMessageBox.question(
            self, t("publish"),
            t("confirm_publish", display, local_version, target_registry.name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        self._set_publish_button_state(pkg_id, busy=True)
        QtWidgets.QApplication.processEvents()

        try:
            self._publisher.publish(pkg_data, pkg_id, target_registry)

            installed_pkgs = self._install_manager._installed["packages"]
            if pkg_id in installed_pkgs:
                installed_pkgs[pkg_id]["source"] = "published"
                self._install_manager._save_installed()

            QtWidgets.QMessageBox.information(
                self, t("publish"), t("publish_success", display),
            )
            self.refresh()
        except Exception as e:
            self._set_publish_button_state(pkg_id, busy=False)
            QtWidgets.QMessageBox.warning(self, t("publish_error"), str(e))

    def _on_unpublish(self, pkg_id, registry_entry):
        if not self._publisher:
            return

        installed = self._install_manager.get_installed_packages()
        pkg_data = installed.get(pkg_id, {})
        display = pkg_data.get("display_name", pkg_id)

        try:
            self._publisher.unpublish(pkg_id, registry_entry)

            # Revert source back to local_script
            installed_pkgs = self._install_manager._installed["packages"]
            if pkg_id in installed_pkgs:
                installed_pkgs[pkg_id]["source"] = "local_script"
                self._install_manager._save_installed()

            QtWidgets.QMessageBox.information(
                self, t("unpublish"),
                t("unpublish_success", display, registry_entry.name),
            )
            self.refresh()
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, t("unpublish_error"), str(e),
            )

    def _set_publish_button_state(self, pkg_id, busy=True):
        for i in range(self._card_layout.count()):
            item = self._card_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, PackageCard) and widget._pkg_id == pkg_id:
                for btn in widget.findChildren(QtWidgets.QPushButton):
                    if btn.text() in (t("publish"), t("publishing")):
                        btn.setText(t("publishing") if busy else t("publish"))
                        btn.setEnabled(not busy)
                        return

    def _on_update(self, pkg_id):
        packages = self._registry_client.get_packages() if self._registry_client else {}
        pkg_data = packages.get(pkg_id)
        if not pkg_data:
            return
        latest = pkg_data.get("latest_version", "")
        display = pkg_data.get("display_name", "")
        reply = QtWidgets.QMessageBox.question(
            self, t("update"),
            t("confirm_update", display, latest),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            self._install_manager.uninstall_package(pkg_id)
        except Exception:
            pass
        self._on_install(pkg_id)

    def _check_self_update(self):
        if not self._self_updater:
            return
        if self._self_updater.has_pending_update():
            ver = self._self_updater.get_pending_version()
            self._update_banner_label.setText(
                t("update_pending", ver)
            )
            self._update_banner_btn.setVisible(False)
            self._update_banner.setVisible(True)
            return
        try:
            result = self._self_updater.check_update()
        except Exception:
            result = None
        if result:
            self._pending_self_update = result  # (version, download_url)
            self._update_banner_label.setText(
                t("update_available", result[0])
            )
            self._update_banner_btn.setVisible(True)
            self._update_banner.setVisible(True)
        else:
            self._update_banner.setVisible(False)

    def _on_self_update(self):
        if not hasattr(self, "_pending_self_update") or not self._pending_self_update:
            return
        version, download_url = self._pending_self_update
        self._update_banner_btn.setText(t("updating"))
        self._update_banner_btn.setEnabled(False)
        QtWidgets.QApplication.processEvents()
        try:
            self._self_updater.stage_update(version, download_url)
            self._update_banner_label.setText(
                t("update_pending", version)
            )
            self._update_banner_btn.setVisible(False)
            self._pending_self_update = None
        except Exception as e:
            self._update_banner_btn.setText(t("update"))
            self._update_banner_btn.setEnabled(True)
            QtWidgets.QMessageBox.warning(self, t("update_error"), str(e))

    def _on_install(self, pkg_id):
        if not self._downloader or not self._install_manager:
            return
        packages = self._registry_client.get_packages() if self._registry_client else {}
        pkg_data = packages.get(pkg_id)
        if not pkg_data:
            return

        self._set_install_button_state(pkg_id, busy=True)
        QtWidgets.QApplication.processEvents()

        pkg_name = pkg_data.get("name", "")
        latest = pkg_data.get("latest_version", "")
        version_info = pkg_data.get("versions", {}).get(latest, {})

        try:
            url = version_info.get("download_url")
            if not url:
                raise RuntimeError(t("no_download_url"))

            dest = os.path.join(
                self._install_manager._config.staging_dir,
                "{}-{}.package".format(pkg_name, latest),
            )
            self._downloader.download(
                url, dest,
                expected_sha256=version_info.get("sha256"),
                expected_size=version_info.get("size_bytes"),
            )

            meta = {
                "id": pkg_id,
                "name": pkg_name,
                "version": latest,
                "type": pkg_data.get("type", "python_package"),
                "display_name": pkg_data.get("display_name", pkg_name),
                "entry_point": {},
            }
            self._install_manager.install_package(dest, meta)

            entry_point = self._resolve_entry_point(pkg_name)
            inst = self._install_manager._installed
            if pkg_id in inst["packages"]:
                inst["packages"][pkg_id]["entry_point"] = entry_point
                self._install_manager._save_installed()

            if os.path.exists(dest):
                os.remove(dest)

            self._rebuild_cards()

        except Exception as e:
            self._set_install_button_state(pkg_id, busy=False)
            QtWidgets.QMessageBox.warning(self, t("install_error"), str(e))

    def _set_install_button_state(self, pkg_id, busy=True):
        for i in range(self._card_layout.count()):
            item = self._card_layout.itemAt(i)
            widget = item.widget()
            if isinstance(widget, PackageCard) and widget._pkg_id == pkg_id:
                for btn in widget.findChildren(QtWidgets.QPushButton):
                    if btn.text() in (t("install"), t("installing")):
                        if busy:
                            btn.setText(t("installing"))
                            btn.setEnabled(False)
                            btn.setStyleSheet(
                                "QPushButton { background: #3a3a3a; color: #666; border: none;"
                                "  border-radius: 6px; padding: 6px; font-weight: 600; font-size: 12px; }"
                            )
                        else:
                            btn.setText(t("install"))
                            btn.setEnabled(True)
                            btn.setStyleSheet(
                                "QPushButton { background: #4CAF50; color: #1e1e1e; border: none;"
                                "  border-radius: 6px; padding: 6px; font-weight: 600; font-size: 12px; }"
                                "QPushButton:hover { background: #5cbf60; }"
                            )
                        return

    def _on_uninstall(self, pkg_id):
        packages = self._registry_client.get_packages() if self._registry_client else {}
        display = packages.get(pkg_id, {}).get("display_name", pkg_id)
        reply = QtWidgets.QMessageBox.question(
            self, t("uninstall"),
            t("confirm_uninstall", display),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self._install_manager.uninstall_package(pkg_id)
            self._rebuild_cards()
            self._stack.setCurrentIndex(0)

    def _on_launch(self, pkg_id):
        installed = self._install_manager.get_installed_packages()
        pkg_data = installed.get(pkg_id, {})
        entry_point = pkg_data.get("entry_point", {})
        try:
            if pkg_data.get("source") in ("local_script", "published") and self._script_manager:
                self._script_manager.launch(pkg_data)
            elif entry_point.get("type") == "exec" and self._script_manager:
                exec_data = dict(pkg_data)
                if not exec_data.get("local_path"):
                    pkg_name = pkg_data.get("name", "")
                    exec_file = entry_point.get("file", "")
                    exec_data["local_path"] = os.path.join(
                        self._install_manager._config.packages_dir, pkg_name, exec_file
                    )
                self._script_manager.launch(exec_data)
            else:
                from carton.core.handlers import get_handler
                handler = get_handler(pkg_data.get("type", "python_package"))
                handler.launch(pkg_data)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, t("launch_error"), str(e))

    def _resolve_entry_point(self, pkg_name):
        packages_dir = self._install_manager._config.packages_dir
        pkg_json_path = os.path.join(packages_dir, pkg_name, "package.json")
        if os.path.exists(pkg_json_path):
            with open(pkg_json_path, "r", encoding="utf-8") as f:
                return json.load(f).get("entry_point", {})
        module_name = pkg_name.replace("-", "_")
        return {"type": "python", "module": module_name, "function": "show"}


def create_window(parent=None):
    if parent is None:
        try:
            import maya.OpenMayaUI as omui
            main_win_ptr = omui.MQtUtil.mainWindow()
            if main_win_ptr:
                parent = wrapInstance(int(main_win_ptr), QtWidgets.QWidget)
        except ImportError:
            pass
    return CartonWindow(parent)
