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
_WINDOW_WIDTH = 780
_WINDOW_HEIGHT = 600


class _IconFetcher(QtCore.QThread):
    """Background thread that downloads remote icons in bulk."""

    icon_ready = QtCore.Signal(str, str)  # (pkg_id, local_path)

    def __init__(self, tasks, config, parent=None):
        """tasks: list of (pkg_id, base_url, pkg_name)"""
        super().__init__(parent)
        self._tasks = tasks
        self._config = config

    def run(self):
        if not self._config:
            return
        cache_dir = os.path.join(self._config.install_dir, ".icon_cache")
        os.makedirs(cache_dir, exist_ok=True)
        for pkg_id, base_url, pkg_name in self._tasks:
            cached = os.path.join(cache_dir, "{}.png".format(pkg_name))
            if os.path.exists(cached):
                self.icon_ready.emit(pkg_id, cached)
                continue
            icon_url = urljoin(base_url, "icons/{}.png".format(pkg_name))
            try:
                req = Request(icon_url)
                resp = urlopen(req, timeout=5)
                data = resp.read()
                with open(cached, "wb") as f:
                    f.write(data)
                self.icon_ready.emit(pkg_id, cached)
            except Exception:
                pass


class _PublishTargetDialog(QtWidgets.QDialog):
    """Dialog to choose a publish target registry."""

    def __init__(self, registries, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("publish"))
        self.setMinimumWidth(360)
        self._result_registry = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        # Dropdown for existing local registries
        if registries:
            label = QtWidgets.QLabel(t("publish_select_registry"))
            label.setStyleSheet("font-weight: 600;")
            layout.addWidget(label)

            self._combo = QtWidgets.QComboBox()
            for r in registries:
                self._combo.addItem(r.name, r)
            layout.addWidget(self._combo)

            select_btn = QtWidgets.QPushButton(t("publish"))
            select_btn.setStyleSheet(
                "QPushButton { background: #98c379; color: white; border: none;"
                "  border-radius: 6px; padding: 8px; font-weight: 600; }"
                "QPushButton:hover { background: #a9d487; }"
            )
            select_btn.clicked.connect(self._on_select)
            layout.addWidget(select_btn)

            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.HLine)
            sep.setStyleSheet("color: #4e5666;")
            layout.addWidget(sep)
        else:
            self._combo = None

        # Create new / Add existing buttons
        new_btn = QtWidgets.QPushButton(t("publish_create_registry"))
        new_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #61afef;"
            "  border: 1px solid #61afef; border-radius: 6px; padding: 8px; }"
            "QPushButton:hover { background: #1d3040; }"
        )
        new_btn.clicked.connect(lambda: self.done(2))
        layout.addWidget(new_btn)

        add_btn = QtWidgets.QPushButton(t("publish_add_existing_registry"))
        add_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #7f848e;"
            "  border: 1px solid #495162; border-radius: 6px; padding: 8px; }"
            "QPushButton:hover { background: #2c313a; }"
        )
        add_btn.clicked.connect(lambda: self.done(3))
        layout.addWidget(add_btn)

    def _on_select(self):
        if self._combo:
            self._result_registry = self._combo.currentData()
        self.accept()

    @property
    def selected_registry(self):
        return self._result_registry



_STYLE = """
QWidget {
    background-color: #282c34;
    color: #abb2bf;
    font-family: "Segoe UI", "Yu Gothic UI", sans-serif;
}
QLineEdit {
    background: #1d1f23;
    border: 1px solid #3e4452;
    border-radius: 6px;
    padding: 7px 12px;
    color: #abb2bf;
    font-size: 13px;
    selection-background-color: #3e4452;
}
QLineEdit:focus {
    border-color: #4d78cc;
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
    background: #4e5666;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #495162;
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
        self._icon_fetcher = None
        self._card_map = {}  # pkg_id -> PackageCard (for deferred icon updates)

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._stack = QtWidgets.QStackedWidget()
        main_layout.addWidget(self._stack)

        # ---- Page 0: Sidebar + Package list ----
        list_page = QtWidgets.QWidget()
        page_layout = QtWidgets.QHBoxLayout(list_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # -- Sidebar --
        sidebar = QtWidgets.QWidget()
        sidebar.setFixedWidth(160)
        sidebar.setStyleSheet("QWidget { background: #21252b; }")
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 12)
        sidebar_layout.setSpacing(4)

        self._sidebar_list = QtWidgets.QListWidget()
        self._sidebar_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { color: #7f848e; padding: 6px 8px; border-radius: 4px; }"
            "QListWidget::item:selected { background: #2c313a; color: #d19a66; border-left: 3px solid #d19a66; }"
            "QListWidget::item:hover { background: #2c313a; }"
            "QListWidget::item:disabled { background: transparent; padding: 0; }"
            "QListWidget::item:disabled:hover { background: transparent; }"
        )
        self._sidebar_list.currentRowChanged.connect(self._on_sidebar_changed)
        sidebar_layout.addWidget(self._sidebar_list)

        # Settings button at bottom of sidebar
        settings_btn = QtWidgets.QPushButton("⚙  " + t("settings_title").split("—")[-1].strip())
        settings_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            "  color: #495162; font-size: 11px; text-align: left; padding: 6px 8px; }"
            "QPushButton:hover { color: #7f848e; }"
        )
        settings_btn.clicked.connect(self._open_settings)
        sidebar_layout.addWidget(settings_btn)

        page_layout.addWidget(sidebar)

        # -- Content area --
        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(10)

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
            "color: #d19a66; font-size: 11px; background: transparent;"
        )
        banner_layout.addWidget(self._update_banner_label)
        banner_layout.addStretch()
        self._update_banner_btn = QtWidgets.QPushButton(t("update"))
        self._update_banner_btn.setFixedHeight(20)
        self._update_banner_btn.setStyleSheet(
            "QPushButton { background: #d19a66; color: white; border: none;"
            "  border-radius: 3px; padding: 0 10px; font-size: 11px; }"
            "QPushButton:hover { background: #e0a972; }"
        )
        self._update_banner_btn.clicked.connect(self._on_self_update)
        self._update_banner_btn.setVisible(False)
        banner_layout.addWidget(self._update_banner_btn)
        content_layout.addWidget(self._update_banner)

        # Search + refresh
        search_row = QtWidgets.QHBoxLayout()
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText(t("search_placeholder"))
        self._search.textChanged.connect(self._filter_cards)
        search_row.addWidget(self._search)

        refresh_btn = QtWidgets.QPushButton("↻")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #3e4452;"
            "  border-radius: 6px; font-size: 16px; color: #5c6370; }"
            "QPushButton:hover { background: #2c313a; color: #abb2bf; border-color: #4e5666; }"
        )
        refresh_btn.clicked.connect(self.refresh)
        search_row.addWidget(refresh_btn)
        content_layout.addLayout(search_row)

        # Toolbar (tabs + register button, visibility depends on sidebar selection)
        toolbar = QtWidgets.QHBoxLayout()

        self._tab_all = QtWidgets.QPushButton(t("tab_all"))
        self._tab_installed = QtWidgets.QPushButton(t("tab_installed"))
        for btn in (self._tab_all, self._tab_installed):
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                "  color: #5c6370; font-size: 12px; padding: 0 12px; }"
                "QPushButton:hover { color: #7f848e; }"
                "QPushButton:checked { color: #d19a66; border-bottom: 2px solid #d19a66; }"
            )
        self._tab_installed.setChecked(True)
        self._tab_all.clicked.connect(lambda: self._set_tab("all"))
        self._tab_installed.clicked.connect(lambda: self._set_tab("installed"))
        toolbar.addWidget(self._tab_installed)
        toolbar.addWidget(self._tab_all)
        toolbar.addStretch()

        self._register_btn = QtWidgets.QPushButton(t("register_script"))
        self._register_btn.setFixedHeight(28)
        self._register_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #3e4452;"
            "  border-radius: 6px; color: #5c6370; font-size: 12px; padding: 0 10px; }"
            "QPushButton:hover { background: #2c313a; color: #abb2bf; border-color: #4e5666; }"
        )
        self._register_btn.clicked.connect(self._on_add_script)
        self._register_btn.setVisible(False)
        toolbar.addWidget(self._register_btn)

        content_layout.addLayout(toolbar)

        # Card list
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._card_container = QtWidgets.QWidget()
        self._card_layout = QtWidgets.QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 10, 0)
        self._card_layout.setSpacing(8)

        self._loading_label = QtWidgets.QLabel(t("loading"))
        self._loading_label.setStyleSheet("color: #5c6370; font-size: 13px; background: transparent;")
        self._loading_label.setAlignment(Qt.AlignCenter)
        self._card_layout.addWidget(self._loading_label)
        self._card_layout.addStretch()

        scroll.setWidget(self._card_container)
        content_layout.addWidget(scroll)

        page_layout.addWidget(content)

        self._stack.addWidget(list_page)

        # ---- Page 1: Detail ----
        self._detail = PackageDetailPanel()
        self._detail.back_requested.connect(lambda: self._stack.setCurrentIndex(0))
        self._detail.install_requested.connect(self._on_install)
        self._detail.uninstall_requested.connect(self._on_uninstall)
        self._detail.launch_requested.connect(self._on_launch)
        self._stack.addWidget(self._detail)

        self._current_tab = "installed"
        self._sidebar_selection = None  # Will be set on refresh

    # ---- public API ----

    def deferred_init(self):
        QtCore.QTimer.singleShot(0, self._do_deferred_init)

    def _do_deferred_init(self):
        self.refresh()
        self._loading_label.setVisible(False)

    def _create_new_registry(self):
        """Create a new empty registry directory. Returns the RegistryEntry or None."""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, t("setup_select_folder"),
        )
        if not folder:
            return None

        name, ok = QtWidgets.QInputDialog.getText(
            self, "Registry Name",
            t("setup_registry_name"),
            text=os.path.basename(folder),
        )
        if not ok or not name:
            return None

        import json
        reg_path = os.path.join(folder, "registry.json")
        if not os.path.exists(reg_path):
            os.makedirs(folder, exist_ok=True)
            with open(reg_path, "w", encoding="utf-8") as f:
                json.dump({"schema_version": "2.0", "packages": {}}, f, indent=2)
            os.makedirs(os.path.join(folder, "packages"), exist_ok=True)

        self._config.add_registry(name, reg_path)
        self._config.save()
        # Return the newly added entry
        return self._config.registries[-1]

    def _add_existing_registry(self):
        """Browse for an existing registry.json. Returns the RegistryEntry or None."""
        path = QtWidgets.QFileDialog.getOpenFileName(
            self, t("settings_select_registry"), "",
            "Registry (registry.json);;JSON (*.json)",
        )[0]
        if not path:
            return None

        base = os.path.basename(os.path.dirname(path))
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Registry Name",
            t("setup_registry_name"),
            text=base,
        )
        if not ok or not name:
            return None

        self._config.add_registry(name, path)
        self._config.save()
        return self._config.registries[-1]

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
        self._rebuild_sidebar()
        self._rebuild_cards()
        self._check_self_update()

    _MYTOOLS_KEY = "__my_tools__"

    def _rebuild_sidebar(self):
        """Rebuild sidebar items from config registries + My Tools."""
        prev = self._sidebar_selection
        self._sidebar_list.blockSignals(True)
        self._sidebar_list.clear()

        packages = self._registry_client.get_packages() if self._registry_client else {}
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}

        # Count packages per registry
        reg_counts = {}
        for pkg_data in packages.values():
            rn = pkg_data.get("_registry_name", "")
            reg_counts[rn] = reg_counts.get(rn, 0) + 1

        # Registry items (config order)
        if self._config:
            for entry in self._config.registries:
                count = reg_counts.get(entry.name, 0)
                item = QtWidgets.QListWidgetItem("{} ({})".format(entry.name, count))
                item.setData(Qt.UserRole, entry.name)
                self._sidebar_list.addItem(item)

        # Separator — use a dedicated widget to avoid hover highlight
        sep = QtWidgets.QListWidgetItem()
        sep.setFlags(Qt.NoItemFlags)
        sep.setSizeHint(QtCore.QSize(0, 13))
        self._sidebar_list.addItem(sep)
        sep_container = QtWidgets.QWidget()
        sep_container.setStyleSheet("background: transparent;")
        sep_lay = QtWidgets.QVBoxLayout(sep_container)
        sep_lay.setContentsMargins(8, 6, 8, 6)
        sep_line = QtWidgets.QFrame()
        sep_line.setFixedHeight(1)
        sep_line.setStyleSheet("background: #3e4452;")
        sep_lay.addWidget(sep_line)
        self._sidebar_list.setItemWidget(sep, sep_container)

        # My Tools
        my_count = sum(
            1 for p in installed.values()
            if p.get("source") in ("local_script", "published")
        )
        my_item = QtWidgets.QListWidgetItem("{} ({})".format(t("my_tools"), my_count))
        my_item.setData(Qt.UserRole, self._MYTOOLS_KEY)
        self._sidebar_list.addItem(my_item)

        # Restore or default selection
        self._sidebar_list.blockSignals(False)
        restored = False
        if prev:
            for i in range(self._sidebar_list.count()):
                item = self._sidebar_list.item(i)
                if item and item.data(Qt.UserRole) == prev:
                    self._sidebar_list.setCurrentRow(i)
                    restored = True
                    break
        if not restored:
            # Default: first registry, or My Tools if no registries
            if self._sidebar_list.count() > 0:
                first = self._sidebar_list.item(0)
                if first and first.flags() & Qt.ItemIsSelectable:
                    self._sidebar_list.setCurrentRow(0)
                else:
                    # Skip separator, select My Tools
                    self._sidebar_list.setCurrentRow(self._sidebar_list.count() - 1)

    def _on_sidebar_changed(self, row):
        """Handle sidebar selection change."""
        item = self._sidebar_list.item(row)
        if not item or not (item.flags() & Qt.ItemIsSelectable):
            return
        self._sidebar_selection = item.data(Qt.UserRole)
        is_my_tools = self._sidebar_selection == self._MYTOOLS_KEY
        # Show tabs for registries, register button for My Tools
        self._tab_all.setVisible(not is_my_tools)
        self._tab_installed.setVisible(not is_my_tools)
        self._register_btn.setVisible(is_my_tools)

        if not is_my_tools:
            # Default to "installed", fall back to "all" if none installed
            packages = self._registry_client.get_packages() if self._registry_client else {}
            installed = self._install_manager.get_installed_packages() if self._install_manager else {}
            has_installed = any(
                pkg_id in installed
                for pkg_id, pkg_data in packages.items()
                if pkg_data.get("_registry_name") == self._sidebar_selection
            )
            self._current_tab = "installed" if has_installed else "all"
            self._tab_installed.setChecked(self._current_tab == "installed")
            self._tab_all.setChecked(self._current_tab == "all")

        self._rebuild_cards()

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
        """Rebuild the card list based on sidebar selection."""
        # Stop any in-flight icon fetcher from a previous rebuild
        if self._icon_fetcher and self._icon_fetcher.isRunning():
            self._icon_fetcher.quit()
            self._icon_fetcher.wait()
            self._icon_fetcher = None
        self._card_map = {}
        icon_fetch_tasks = []

        while self._card_layout.count() > 1:
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        packages = self._registry_client.get_packages() if self._registry_client else {}
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}
        selection = self._sidebar_selection

        visible_items = []

        if selection == self._MYTOOLS_KEY:
            # My Tools: show locally registered scripts
            for pkg_id, pkg_data in installed.items():
                if pkg_data.get("source") in ("local_script", "published"):
                    item = dict(pkg_data)
                    item["_installed_ver"] = pkg_data.get("version")
                    item["_local_script"] = True
                    visible_items.append((pkg_id, item))
            visible_items.sort(key=lambda x: x[1].get("display_name", ""))
        else:
            # Registry view: show packages from selected registry
            for pkg_id, pkg_data in packages.items():
                if pkg_data.get("_registry_name") != selection:
                    continue
                item = dict(pkg_data)
                is_installed = pkg_id in installed
                if is_installed:
                    item["_installed_ver"] = installed[pkg_id].get("version")
                    inst = installed[pkg_id]
                    if inst.get("source") in ("local_script", "published") and inst.get("local_path"):
                        item["_local_script"] = True
                if self._current_tab == "installed" and not is_installed:
                    continue
                visible_items.append((pkg_id, item))
            visible_items.sort(key=lambda x: x[1].get("display_name", ""))

        for pkg_id, pkg_data in visible_items:
            installed_ver = pkg_data.get("_installed_ver")
            pkg_name = pkg_data.get("name", "")

            # Icon resolution
            icon_path = None
            icon_value = pkg_data.get("icon", "")
            if isinstance(icon_value, bool) and icon_value:
                base_dir = pkg_data.get("_registry_base_dir", "")
                is_remote = pkg_data.get("_registry_remote", False)
                if base_dir:
                    if is_remote:
                        if self._config:
                            cached = os.path.join(
                                self._config.install_dir, ".icon_cache",
                                "{}.png".format(pkg_name),
                            )
                            if os.path.exists(cached):
                                icon_path = cached
                            else:
                                icon_fetch_tasks.append((pkg_id, base_dir, pkg_name))
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
            self._card_map[pkg_id] = card

            is_local = pkg_data.get("_local_script", False)
            is_published_local = (pkg_id in installed and
                                  installed[pkg_id].get("source") in ("local_script", "published"))
            if is_local or is_published_local:
                card.mousePressEvent = lambda e, pid=pkg_id: self._show_edit(pid)
            else:
                card.mousePressEvent = lambda e, pid=pkg_id: self._show_detail(pid)

            idx = self._card_layout.count() - 1
            self._card_layout.insertWidget(idx, card)

        # Start background icon download for uncached remote icons
        if icon_fetch_tasks:
            self._icon_fetcher = _IconFetcher(icon_fetch_tasks, self._config, parent=self)
            self._icon_fetcher.icon_ready.connect(self._on_icon_ready)
            self._icon_fetcher.start()

    def _on_icon_ready(self, pkg_id, icon_path):
        """Slot called from background thread when an icon is downloaded."""
        card = self._card_map.get(pkg_id)
        if card:
            card.set_icon(icon_path)

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
            pkg_data["homepage"] = result["homepage"]
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

        # Select target registry for publishing
        registries = [r for r in self._config.registries if not r.is_remote]
        dlg = _PublishTargetDialog(registries, parent=self)
        result = dlg.exec_()

        if result == 0:  # Rejected / cancelled
            return
        elif result == 1:  # Accepted — selected from dropdown
            target_registry = dlg.selected_registry
            if not target_registry:
                return
        elif result == 2:  # Create new registry
            target_registry = self._create_new_registry()
            if not target_registry:
                return
        elif result == 3:  # Add existing registry
            target_registry = self._add_existing_registry()
            if not target_registry:
                return
        else:
            return

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
                "{}-{}.zip".format(pkg_name, latest),
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
                                "QPushButton { background: #4e5666; color: #5c6370; border: none;"
                                "  border-radius: 6px; padding: 6px; font-weight: 600; font-size: 12px; }"
                            )
                        else:
                            btn.setText(t("install"))
                            btn.setEnabled(True)
                            btn.setStyleSheet(
                                "QPushButton { background: #98c379; color: #282c34; border: none;"
                                "  border-radius: 6px; padding: 6px; font-weight: 600; font-size: 12px; }"
                                "QPushButton:hover { background: #a9d487; }"
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
