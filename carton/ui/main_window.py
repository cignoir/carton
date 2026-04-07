"""Carton main window."""

import json
import os
from collections import OrderedDict

from carton.compat_urllib import urlopen, Request, URLError, urljoin
from carton.ui.compat import QtWidgets, QtCore, Qt, wrapInstance
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.package_card import PackageCard
from carton.ui.package_detail import PackageDetailPanel
from carton.ui.settings_dialog import SettingsDialog
from carton.ui.add_dialog import AddDialog
from carton.ui.edit_dialog import EditDialog

_WINDOW_TITLE = "Carton"
_WINDOW_WIDTH = 780
_WINDOW_HEIGHT = 600


def _icon_filename(pkg_data):
    """Return the bare icon filename (e.g. ``"AriMirror.png"``) for a package.

    Resolution order:
      1. If ``icon`` is a string ending in an image extension, treat it as the
         filename and return its basename verbatim — this preserves whatever
         the package author chose, including PascalCase / non-ASCII names.
      2. If ``icon`` is ``True`` (legacy), fall back to ``<name>.png``.
      3. Otherwise return None.
    """
    icon_value = pkg_data.get("icon", "")
    if isinstance(icon_value, str) and icon_value.endswith((".png", ".jpg", ".svg")):
        return os.path.basename(icon_value)
    if isinstance(icon_value, bool) and icon_value:
        name = pkg_data.get("name", "")
        if name:
            return "{}.png".format(name)
    return None


class _IconFetcher(QtCore.QThread):
    """Background thread that downloads remote icons in bulk."""

    icon_ready = QtCore.Signal(str, str)  # (pkg_id, local_path)

    def __init__(self, tasks, config, parent=None):
        """tasks: list of (pkg_id, base_url, icon_filename)"""
        super().__init__(parent)
        self._tasks = tasks
        self._config = config

    def run(self):
        if not self._config:
            return
        cache_dir = self._config.icon_cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        for pkg_id, base_url, icon_filename in self._tasks:
            cached = os.path.join(cache_dir, icon_filename)
            if os.path.exists(cached):
                # Touch atime so the LRU eviction sees this file as "used".
                try:
                    os.utime(cached, None)
                except OSError:
                    pass
                self.icon_ready.emit(pkg_id, cached)
                continue
            icon_url = urljoin(base_url, "icons/{}".format(icon_filename))
            try:
                req = Request(icon_url)
                resp = urlopen(req, timeout=5)
                data = resp.read()
                with open(cached, "wb") as f:
                    f.write(data)
                self.icon_ready.emit(pkg_id, cached)
            except Exception:
                pass
        # Keep the cache from growing unboundedly across sessions.
        from carton.core.icon_cache import enforce_size_limit
        enforce_size_limit(cache_dir)


class _SelfUpdateCheckWorker(QtCore.QThread):
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
                theme.btn_outline(theme.ACCENT_GREEN, theme.ACCENT_GREEN_HOVER)
            )
            select_btn.clicked.connect(self._on_select)
            layout.addWidget(select_btn)

            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.HLine)
            sep.setStyleSheet("color: {};".format(theme.BORDER_HOVER))
            layout.addWidget(sep)
        else:
            self._combo = None

        # Create new / Add existing buttons
        new_btn = QtWidgets.QPushButton(t("publish_create_registry"))
        new_btn.setStyleSheet(
            theme.btn_outline(theme.ACCENT_LINK, "#1d3040")
        )
        new_btn.clicked.connect(lambda: self.done(2))
        layout.addWidget(new_btn)

        add_btn = QtWidgets.QPushButton(t("publish_add_existing_registry"))
        add_btn.setStyleSheet(
            theme.btn_outline(theme.TEXT_SECONDARY, theme.BG_HOVER)
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



_STYLE = theme.MAIN_STYLE


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
        self._mytools_collapsed = set()  # ns keys collapsed in My Tools view
        self._mytools_groups = {}  # ns key -> (header_btn, [cards])
        self._update_check_worker = None

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
        sidebar.setFixedWidth(180)
        sidebar.setStyleSheet("QWidget {{ background: {}; }}".format(theme.BG_SIDEBAR))
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 14, 10, 10)
        sidebar_layout.setSpacing(0)

        # Section caption style — small uppercase tracking, used by every
        # sidebar section so the visual rhythm comes from typography +
        # whitespace, not from hairlines.
        caption_css = (
            "color: {c}; font-size: 10px; font-weight: 800;"
            " letter-spacing: 2px; padding: 4px 8px 4px 8px;"
            " background: transparent;"
        ).format(c=theme.TEXT_PRIMARY)
        self._sidebar_caption_css = caption_css

        def make_caption_row(text, collapsible_target=None):
            """Caption label + dashed rule on its right.

            If ``collapsible_target`` is given, the caption becomes a
            clickable button that toggles the target widget's visibility
            and shows a chevron next to the text.
            """
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 6, 8, 2)
            row.setSpacing(6)

            if collapsible_target is None:
                lbl = QtWidgets.QLabel(text)
                lbl.setStyleSheet(caption_css)
                row.addWidget(lbl)
            else:
                btn = QtWidgets.QPushButton("\u25bc  " + text)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(
                    "QPushButton {{ {base} border: none; text-align: left; }}"
                    "QPushButton:hover {{ color: {hover}; }}"
                    .format(base=caption_css, hover=theme.ACCENT_ORANGE)
                )

                def toggle(_=False, b=btn, target=collapsible_target, label=text):
                    visible = not target.isVisible()
                    target.setVisible(visible)
                    arrow = "\u25bc" if visible else "\u25b6"
                    b.setText("{}  {}".format(arrow, label))

                btn.clicked.connect(toggle)
                row.addWidget(btn)

            rule = QtWidgets.QFrame()
            rule.setFixedHeight(1)
            rule.setStyleSheet(
                "background: transparent;"
                " border: none; border-top: 1px dashed {};".format(theme.BORDER_HOVER)
            )
            row.addWidget(rule, stretch=1)
            return row

        # ----- Profile section ----------------------------------------------
        profile_container = QtWidgets.QWidget()
        profile_row = QtWidgets.QHBoxLayout(profile_container)
        profile_row.setContentsMargins(0, 0, 0, 0)
        profile_row.setSpacing(4)

        self._profile_combo = QtWidgets.QComboBox()
        self._profile_combo.setStyleSheet(theme.combobox_style())
        self._profile_combo.currentIndexChanged.connect(self._on_profile_combo_changed)
        profile_row.addWidget(self._profile_combo, stretch=1)

        manage_btn = QtWidgets.QToolButton()
        manage_btn.setText("\u2699")  # gear
        manage_btn.setToolTip(t("profile_manage"))
        manage_btn.setCursor(Qt.PointingHandCursor)
        manage_btn.setFixedSize(26, 26)
        manage_btn.setStyleSheet(
            "QToolButton {{ background: {bg2}; border: 1px solid {border};"
            "  border-radius: 4px; color: {muted}; font-size: 14px; }}"
            "QToolButton:hover {{ color: {text}; border-color: {border_h};"
            "  background: {hover}; }}".format(
                bg2=theme.BG_SECONDARY, border=theme.BORDER,
                border_h=theme.BORDER_HOVER, muted=theme.TEXT_MUTED,
                text=theme.TEXT_PRIMARY, hover=theme.BG_HOVER)
        )
        manage_btn.clicked.connect(self._open_profile_manager)
        profile_row.addWidget(manage_btn)

        sidebar_layout.addLayout(make_caption_row(
            t("profile_label").upper(), collapsible_target=profile_container,
        ))
        sidebar_layout.addWidget(profile_container)
        sidebar_layout.addSpacing(16)

        # ----- Registries section -------------------------------------------
        self._registry_list = QtWidgets.QListWidget()
        self._registry_list.setStyleSheet(theme.sidebar_list_style())
        self._registry_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._registry_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._registry_list.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        self._registry_list.currentRowChanged.connect(self._on_registry_row_changed)
        sidebar_layout.addLayout(make_caption_row(
            t("sidebar_library").upper(), collapsible_target=self._registry_list,
        ))
        sidebar_layout.addWidget(self._registry_list)

        sidebar_layout.addSpacing(16)

        # ----- My Tools section ---------------------------------------------
        self._mytools_list = QtWidgets.QListWidget()
        self._mytools_list.setStyleSheet(theme.sidebar_list_style())
        self._mytools_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._mytools_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._mytools_list.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        self._mytools_list.currentRowChanged.connect(self._on_mytools_row_changed)
        sidebar_layout.addLayout(make_caption_row(
            t("my_tools").upper(), collapsible_target=self._mytools_list,
        ))
        sidebar_layout.addWidget(self._mytools_list)

        sidebar_layout.addStretch(1)

        # ----- Footer --------------------------------------------------------
        sidebar_layout.addSpacing(8)
        settings_btn = QtWidgets.QPushButton("⚙  " + t("settings_title").split("—")[-1].strip())
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.setStyleSheet(
            "QPushButton {{ background: transparent; border: none;"
            "  color: {sec}; font-size: 11px; text-align: left;"
            "  padding: 8px 6px; border-top: 1px solid {border}; }}"
            "QPushButton:hover {{ color: {text}; }}".format(
                sec=theme.TEXT_PRIMARY, text=theme.ACCENT_ORANGE,
                border=theme.BORDER)
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
        )  # Unique banner colors intentionally not in theme
        self._update_banner.setVisible(False)
        banner_layout = QtWidgets.QHBoxLayout(self._update_banner)
        banner_layout.setContentsMargins(10, 0, 6, 0)
        banner_layout.setSpacing(8)
        self._update_banner_label = QtWidgets.QLabel()
        self._update_banner_label.setStyleSheet(
            "color: {}; font-size: 11px; background: transparent;".format(theme.ACCENT_ORANGE)
        )
        banner_layout.addWidget(self._update_banner_label)
        banner_layout.addStretch()
        self._update_banner_btn = QtWidgets.QPushButton(t("update"))
        self._update_banner_btn.setFixedHeight(20)
        self._update_banner_btn.setStyleSheet(
            "QPushButton {{ background: {bg}; color: white; border: none;"
            "  border-radius: 3px; padding: 0 10px; font-size: 11px; }}"
            "QPushButton:hover {{ background: {hover}; }}".format(
                bg=theme.ACCENT_ORANGE, hover=theme.ACCENT_ORANGE_HOVER)
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
            "QPushButton {{ background: transparent; border: 1px solid {border};"
            "  border-radius: 6px; font-size: 16px; color: {dim}; }}"
            "QPushButton:hover {{ background: {hover}; color: {text};"
            "  border-color: {border_hover}; }}".format(
                border=theme.BORDER, dim=theme.TEXT_PRIMARY, hover=theme.BG_HOVER,
                text=theme.ACCENT_ORANGE, border_hover=theme.BORDER_HOVER)
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
                "QPushButton {{ background: transparent; border: none;"
                "  color: {dim}; font-size: 12px; padding: 0 12px; }}"
                "QPushButton:hover {{ color: {sec}; }}"
                "QPushButton:checked {{ color: {orange};"
                "  border-bottom: 2px solid {orange}; }}".format(
                    dim=theme.TEXT_SECONDARY, sec=theme.TEXT_PRIMARY,
                    orange=theme.ACCENT_ORANGE)
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
            "QPushButton {{ background: transparent; border: 1px solid {border};"
            "  border-radius: 6px; color: {dim}; font-size: 12px; padding: 0 10px; }}"
            "QPushButton:hover {{ background: {hover}; color: {text};"
            "  border-color: {border_hover}; }}".format(
                border=theme.BORDER, dim=theme.TEXT_PRIMARY, hover=theme.BG_HOVER,
                text=theme.ACCENT_ORANGE, border_hover=theme.BORDER_HOVER)
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
        self._loading_label.setStyleSheet(
            "color: {}; font-size: 13px; background: transparent;".format(theme.TEXT_DIM)
        )
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
        self._detail.rollback_requested.connect(self._on_rollback)
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
        self._rebuild_profile_combo()

    def _rebuild_profile_combo(self):
        if not self._config:
            return
        from carton.core import profile_store
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        names = profile_store.ordered_profiles(self._config.profile_order)
        for name in names:
            self._profile_combo.addItem(name, name)
        active = self._config.active_profile or profile_store.DEFAULT_PROFILE_NAME
        idx = self._profile_combo.findData(active)
        if idx < 0:
            idx = 0
        self._profile_combo.setCurrentIndex(idx)
        self._profile_combo.blockSignals(False)

    def _on_profile_combo_changed(self, index):
        if not self._config or index < 0:
            return
        new_name = self._profile_combo.itemData(index) or ""
        if new_name == self._config.active_profile:
            return
        self._switch_profile(new_name)

    def _switch_profile(self, name):
        from carton.core import profile_store
        from carton.core.profile import InvalidProfileError
        if not name:
            name = profile_store.DEFAULT_PROFILE_NAME
        try:
            profile = profile_store.load_profile(name)
        except InvalidProfileError as e:
            QtWidgets.QMessageBox.warning(self, "Carton", str(e))
            self._rebuild_profile_combo()
            return
        self._config.apply_profile(profile)
        self._config.active_profile = name
        self._config.save()
        self._config.apply_proxy_to_env()
        self.refresh()

    def _open_profile_manager(self):
        from carton.ui.profile_manager_dialog import ProfileManagerDialog
        dlg = ProfileManagerDialog(self._config, parent=self)
        dlg.exec_()
        self._rebuild_profile_combo()
        # The user may have edited the active profile — reapply just in case.
        if self._config.active_profile:
            try:
                from carton.core import profile_store
                profile = profile_store.load_profile(self._config.active_profile)
                self._config.apply_profile(profile)
                self._config.save()
                self.refresh()
            except Exception:
                pass

    def refresh(self):
        if not self._registry_client:
            return
        self._registry_client.fetch()
        self._rebuild_sidebar()
        self._rebuild_cards()
        self._check_self_update()

    _MYTOOLS_KEY = "__my_tools__"
    _MYTOOLS_NS_PREFIX = "__my_tools__:"

    def _is_mytools_selection(self, key):
        return key == self._MYTOOLS_KEY or (
            isinstance(key, str) and key.startswith(self._MYTOOLS_NS_PREFIX)
        )

    def _mytools_ns_filter(self, key):
        """Return the namespace key if selection is a child, else None."""
        if isinstance(key, str) and key.startswith(self._MYTOOLS_NS_PREFIX):
            return key[len(self._MYTOOLS_NS_PREFIX):]
        return None

    def _rebuild_sidebar(self):
        """Rebuild sidebar items from config registries + My Tools."""
        prev = self._sidebar_selection
        for lst in (self._registry_list, self._mytools_list):
            lst.blockSignals(True)
            lst.clear()

        packages = self._registry_client.get_packages() if self._registry_client else {}
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}

        # Count packages per registry
        reg_counts = {}
        for pkg_data in packages.values():
            rn = pkg_data.get("_registry_name", "")
            reg_counts[rn] = reg_counts.get(rn, 0) + 1

        # Registries
        if self._config:
            for entry in self._config.registries:
                count = reg_counts.get(entry.name, 0)
                item = QtWidgets.QListWidgetItem("{} ({})".format(entry.name, count))
                item.setData(Qt.UserRole, entry.name)
                self._registry_list.addItem(item)

        # My Tools — All + namespace children
        my_pkgs = [
            p for p in installed.values()
            if p.get("source") in ("local_script", "published")
        ]
        my_count = len(my_pkgs)
        all_item = QtWidgets.QListWidgetItem("{} ({})".format(t("my_tools_all"), my_count))
        all_item.setData(Qt.UserRole, self._MYTOOLS_KEY)
        self._mytools_list.addItem(all_item)

        ns_counts = {}
        for p in my_pkgs:
            ns = (p.get("namespace") or "").lower()
            ns_counts[ns] = ns_counts.get(ns, 0) + 1
        for ns in sorted(ns_counts.keys(), key=lambda k: (k == "", k)):
            label = ns if ns else t("my_tools_no_namespace")
            child = QtWidgets.QListWidgetItem("{} ({})".format(label, ns_counts[ns]))
            child.setData(Qt.UserRole, self._MYTOOLS_NS_PREFIX + ns)
            self._mytools_list.addItem(child)

        for lst in (self._registry_list, self._mytools_list):
            lst.blockSignals(False)

        # Restore or default selection
        if not self._restore_sidebar_selection(prev):
            # Default: first registry; fall back to My Tools "All"
            if self._registry_list.count() > 0:
                self._registry_list.setCurrentRow(0)
            elif self._mytools_list.count() > 0:
                self._mytools_list.setCurrentRow(0)

    def _restore_sidebar_selection(self, key):
        if not key:
            return False
        if self._is_mytools_selection(key):
            for i in range(self._mytools_list.count()):
                if self._mytools_list.item(i).data(Qt.UserRole) == key:
                    self._mytools_list.setCurrentRow(i)
                    return True
        else:
            for i in range(self._registry_list.count()):
                if self._registry_list.item(i).data(Qt.UserRole) == key:
                    self._registry_list.setCurrentRow(i)
                    return True
        return False

    def _on_registry_row_changed(self, row):
        if row < 0:
            return
        item = self._registry_list.item(row)
        if not item:
            return
        # Clear the My Tools selection so only one row in the sidebar is
        # ever highlighted at a time.
        self._mytools_list.blockSignals(True)
        self._mytools_list.clearSelection()
        self._mytools_list.setCurrentRow(-1)
        self._mytools_list.blockSignals(False)
        self._apply_sidebar_selection(item.data(Qt.UserRole))

    def _on_mytools_row_changed(self, row):
        if row < 0:
            return
        item = self._mytools_list.item(row)
        if not item:
            return
        self._registry_list.blockSignals(True)
        self._registry_list.clearSelection()
        self._registry_list.setCurrentRow(-1)
        self._registry_list.blockSignals(False)
        self._apply_sidebar_selection(item.data(Qt.UserRole))

    def _apply_sidebar_selection(self, key):
        """Common path for both sidebar lists."""
        self._sidebar_selection = key
        is_my_tools = self._is_mytools_selection(self._sidebar_selection)
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

    def _resolve_icon_path(self, pkg_data):
        """Resolve an icon file path from package data. Returns path or None."""
        icon_value = pkg_data.get("icon", "")
        # Absolute file path on disk (locally registered scripts)
        if (isinstance(icon_value, str)
                and icon_value.endswith((".png", ".jpg", ".svg"))
                and os.path.isabs(icon_value)
                and os.path.exists(icon_value)):
            return icon_value

        icon_filename = _icon_filename(pkg_data)
        if not icon_filename:
            return None

        base_dir = pkg_data.get("_registry_base_dir", "")
        is_remote = pkg_data.get("_registry_remote", False)
        if not base_dir:
            return None
        if is_remote:
            if self._config:
                cached = os.path.join(
                    self._config.icon_cache_dir, icon_filename,
                )
                if os.path.exists(cached):
                    return cached
        else:
            candidate = os.path.join(base_dir, "icons", icon_filename)
            if os.path.exists(candidate):
                return candidate
        return None

    def _fetch_remote_icon(self, base_url, icon_filename):
        """Download a remote icon and cache locally. Returns local path or None."""
        if not self._config or not icon_filename:
            return None
        cache_dir = self._config.icon_cache_dir
        cached = os.path.join(cache_dir, icon_filename)
        if os.path.exists(cached):
            return cached

        icon_url = urljoin(base_url, "icons/{}".format(icon_filename))
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

        # Build a reverse index: pkg_id -> [writable local registry names]
        # so each card can show its Published-to badge without re-reading
        # every registry.json per card.
        published_map = self._build_published_map()

        visible_items = []

        if self._is_mytools_selection(selection):
            ns_filter = self._mytools_ns_filter(selection)
            # My Tools: show locally registered scripts, grouped by namespace
            for pkg_id, pkg_data in installed.items():
                if pkg_data.get("source") not in ("local_script", "published"):
                    continue
                if ns_filter is not None:
                    pkg_ns = (pkg_data.get("namespace") or "").lower()
                    if pkg_ns != ns_filter:
                        continue
                item = dict(pkg_data)
                item["_installed_ver"] = pkg_data.get("version")
                item["_local_script"] = True
                visible_items.append((pkg_id, item))
            visible_items.sort(key=lambda x: (
                (x[1].get("namespace") or "~").lower(),
                x[1].get("display_name", ""),
            ))
        else:
            # Registry view: show packages from selected registry
            for pkg_id, pkg_data in packages.items():
                if pkg_data.get("_registry_name") != selection:
                    continue
                item = dict(pkg_data)
                # A demoted (uninstalled-from-registry) entry stays in
                # installed.json with source=local_script so it remains in
                # My Tools, but the registry view should show it as
                # not-installed so the user can re-install if they want.
                inst_entry = installed.get(pkg_id, {})
                is_installed = (
                    pkg_id in installed
                    and inst_entry.get("source") != "local_script"
                )
                if is_installed:
                    inst = installed[pkg_id]
                    item["_installed_ver"] = inst.get("version")
                    # Surface the recorded sha256 so the card can render
                    # the verified badge — registry view shows it from the
                    # installed.json snapshot, not from the live registry.
                    if inst.get("sha256"):
                        item["sha256"] = inst.get("sha256")
                    if inst.get("pinned"):
                        item["pinned"] = True
                    if inst.get("source") in ("local_script", "published") and inst.get("local_path"):
                        item["_local_script"] = True
                if self._current_tab == "installed" and not is_installed:
                    continue
                visible_items.append((pkg_id, item))
            visible_items.sort(key=lambda x: x[1].get("display_name", ""))

        is_my_tools_view = (selection == self._MYTOOLS_KEY)  # only "All", not ns children
        current_ns = None
        ns_groups = {}  # ns_key -> (header_btn, [card widgets])
        for pkg_id, pkg_data in visible_items:
            if is_my_tools_view:
                ns = (pkg_data.get("namespace") or "").lower()
                if ns != current_ns:
                    current_ns = ns
                    label_text = ns if ns else t("my_tools_no_namespace")
                    collapsed = ns in self._mytools_collapsed
                    arrow = "\u25b6" if collapsed else "\u25bc"
                    header = QtWidgets.QPushButton("{}  {}".format(arrow, label_text))
                    header.setCursor(Qt.PointingHandCursor)
                    header.setStyleSheet(
                        "QPushButton {{ color: {dim}; background: transparent;"
                        " font-size: 11px; font-weight: bold; text-align: left;"
                        " padding: 8px 4px 4px 4px; border: none;"
                        " border-bottom: 1px solid {border}; }}"
                        "QPushButton:hover {{ color: {text}; }}"
                        .format(dim=theme.TEXT_DIM, border=theme.BORDER,
                                text=theme.TEXT_PRIMARY)
                    )
                    ns_groups[ns] = (header, [])
                    header.clicked.connect(
                        lambda _checked=False, k=ns: self._toggle_mytools_group(k)
                    )
                    idx = self._card_layout.count() - 1
                    self._card_layout.insertWidget(idx, header)
            installed_ver = pkg_data.get("_installed_ver")
            pkg_name = pkg_data.get("name", "")

            # Icon resolution
            icon_path = self._resolve_icon_path(pkg_data)
            if not icon_path:
                icon_filename = _icon_filename(pkg_data)
                base_dir = pkg_data.get("_registry_base_dir", "")
                is_remote = pkg_data.get("_registry_remote", False)
                if icon_filename and is_remote and base_dir:
                    icon_fetch_tasks.append((pkg_id, base_dir, icon_filename))

            # In a registry view we render the same plain consumer card
            # regardless of whether the user happens to own the package:
            # no Publish button, no "published-to" badge, no Edit click.
            # Those affordances only make sense in My Tools.
            in_my_tools_view = self._is_mytools_selection(selection)
            if in_my_tools_view:
                card_pkg_data = pkg_data
                card_published = published_map.get(pkg_id, [])
            else:
                card_pkg_data = {
                    k: v for k, v in pkg_data.items() if k != "_local_script"
                }
                card_published = []

            card = PackageCard(
                pkg_id, card_pkg_data,
                installed_version=installed_ver,
                icon_path=icon_path,
                published_registries=card_published,
            )
            card.launch_requested.connect(self._on_launch)
            card.install_requested.connect(self._on_install)
            card.publish_requested.connect(self._on_publish)
            card.update_requested.connect(self._on_update)
            card.unpublish_requested.connect(self._on_card_unpublish)
            card.setCursor(Qt.PointingHandCursor)
            self._card_map[pkg_id] = card

            # Edit only opens from My Tools view. In a registry view the
            # user is acting as a consumer — even for packages they
            # published — so show the detail panel (with rollback /
            # version history) instead.
            if self._is_mytools_selection(selection):
                card.mousePressEvent = lambda e, pid=pkg_id: self._show_edit(pid)
            else:
                card.mousePressEvent = lambda e, pid=pkg_id: self._show_detail(pid)

            idx = self._card_layout.count() - 1
            self._card_layout.insertWidget(idx, card)
            if is_my_tools_view and current_ns in ns_groups:
                ns_groups[current_ns][1].append(card)

        # Apply initial collapsed state for My Tools groups
        self._mytools_groups = ns_groups
        for ns_key, (_hdr, cards) in ns_groups.items():
            if ns_key in self._mytools_collapsed:
                for c in cards:
                    c.setVisible(False)

        # Start background icon download for uncached remote icons
        if icon_fetch_tasks:
            self._icon_fetcher = _IconFetcher(icon_fetch_tasks, self._config, parent=self)
            self._icon_fetcher.icon_ready.connect(self._on_icon_ready)
            self._icon_fetcher.start()

    def _toggle_mytools_group(self, ns_key):
        group = self._mytools_groups.get(ns_key)
        if not group:
            return
        header, cards = group
        if ns_key in self._mytools_collapsed:
            self._mytools_collapsed.discard(ns_key)
            visible = True
        else:
            self._mytools_collapsed.add(ns_key)
            visible = False
        for c in cards:
            c.setVisible(visible)
        # Update arrow in header text (first 1 char + 2 spaces + label)
        text = header.text()
        if len(text) >= 3:
            new_arrow = "\u25bc" if visible else "\u25b6"
            header.setText(new_arrow + text[1:])

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

        # Resolve icon path for the detail panel
        icon_path = self._resolve_icon_path(pkg_data)

        self._detail.show_package(pkg_id, pkg_data, installed_version=installed_ver,
                                  icon_path=icon_path)
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
        if result["action"] == "history":
            self._show_history_for(pkg_id)
            return
        if result["action"] == "unpublish":
            self._on_unpublish(pkg_id, result["registry"])
            return
        if result["action"] == "remove":
            if self._script_manager:
                self._script_manager.unregister(pkg_id)
            self._rebuild_sidebar()
            self._rebuild_cards()
        elif result["action"] == "save":
            pkg_data["display_name"] = result["display_name"]
            pkg_data["version"] = result["version"]
            pkg_data["author"] = result["author"]
            pkg_data["icon"] = result["icon"]
            pkg_data["homepage"] = result["homepage"]
            pkg_data["description"] = result["description"]
            pkg_data["entry_point"] = result["entry_point"]
            pkg_data["include_compiled"] = result.get("include_compiled", False)

            new_ns = result.get("namespace", "")
            old_ns = pkg_data.get("namespace", "")
            installed_pkgs = self._install_manager._installed["packages"]
            if new_ns != old_ns and not published_regs:
                # Slugify + validate; the dialog should already have shown a
                # preview but be defensive in case it didn't.
                if new_ns:
                    from carton.core.identity import (
                        slugify_namespace, validate_namespace, InvalidIdentityError,
                    )
                    new_ns = slugify_namespace(new_ns)
                    try:
                        new_ns = validate_namespace(new_ns)
                    except InvalidIdentityError as e:
                        QtWidgets.QMessageBox.warning(self, t("register_error"), str(e))
                        return
                pkg_data["namespace"] = new_ns
                name = pkg_data.get("name", "")
                new_pkg_id = "{}/{}".format(new_ns, name) if new_ns else name
                if new_pkg_id != pkg_id:
                    installed_pkgs.pop(pkg_id, None)
                    installed_pkgs[new_pkg_id] = pkg_data
                else:
                    installed_pkgs[pkg_id] = pkg_data
            else:
                installed_pkgs[pkg_id] = pkg_data
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
        dialog = SettingsDialog(self._config, self, self_updater=self._self_updater)
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
                namespace=result.get("namespace", ""),
                home_registry=result.get("home_registry"),
                include_compiled=result.get("include_compiled", False),
            )
            self._rebuild_sidebar()
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

        # Home registry mismatch warning
        home_reg = pkg_data.get("home_registry") or {}
        home_name = home_reg.get("name", "")
        if home_name and home_name != target_registry.name:
            reply = QtWidgets.QMessageBox.question(
                self, t("publish"),
                t("publish_home_registry_mismatch", home_name, target_registry.name),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return

        # Ensure namespace is set; prompt if not
        namespace = pkg_data.get("namespace", "")
        if not namespace:
            from carton.core.identity import slugify_namespace
            ns, ok = QtWidgets.QInputDialog.getText(
                self, t("publish"),
                t("publish_namespace_prompt"),
            )
            if not ok or not ns.strip():
                return
            namespace = slugify_namespace(ns)
            if not namespace:
                return
            # Persist immediately so subsequent publishes don't re-ask
            installed_pkgs = self._install_manager._installed["packages"]
            if pkg_id in installed_pkgs:
                installed_pkgs[pkg_id]["namespace"] = namespace
                self._install_manager._save_installed()

        # Confirm + collect release notes in one dialog so the user only
        # gets prompted once. Cancel returns without publishing.
        from carton.ui.publish_confirm_dialog import PublishConfirmDialog
        confirm = PublishConfirmDialog(
            display, local_version, target_registry.name, parent=self,
        )
        if confirm.exec_() != QtWidgets.QDialog.Accepted:
            return
        release_notes = confirm.release_notes()

        self._set_publish_button_state(pkg_id, busy=True)
        QtWidgets.QApplication.processEvents()

        try:
            result = self._publisher.publish(
                pkg_data, target_registry, namespace=namespace,
                release_notes=release_notes,
            )

            new_pkg_id = result["id"]
            installed_pkgs = self._install_manager._installed["packages"]
            # Re-key the installed entry under the canonical namespace/name
            if pkg_id in installed_pkgs:
                entry = installed_pkgs.pop(pkg_id)
                entry["namespace"] = result["namespace"]
                entry["name"] = result["name"]
                entry["source"] = "published"
                entry.setdefault("home_registry", {"name": target_registry.name})
                installed_pkgs[new_pkg_id] = entry
                self._install_manager._save_installed()

            warnings = result.get("warnings") or []
            msg = t("publish_success", display)
            if warnings:
                msg += "\n\nWarnings:\n  - " + "\n  - ".join(warnings)
            QtWidgets.QMessageBox.information(self, t("publish"), msg)
            self.refresh()
        except Exception as e:
            self._set_publish_button_state(pkg_id, busy=False)
            from carton.core.publisher import VersionConflictError, MissingNamespaceError
            if isinstance(e, VersionConflictError):
                msg = t("publish_already_published", e.version)
            elif isinstance(e, MissingNamespaceError):
                msg = str(e)
            else:
                msg = str(e)
            QtWidgets.QMessageBox.warning(self, t("publish_error"), msg)

    def _build_published_map(self):
        """Return ``{pkg_id: [registry_name, ...]}`` for all writable local
        registries, built from a single pass over each registry.json.

        Remote registries are excluded: the user cannot unpublish from them,
        so there's no reason to surface the badge for those.
        """
        result = {}
        if not self._config:
            return result
        for entry in self._config.registries:
            if entry.is_remote:
                continue
            reg_path = os.path.normpath(entry.path)
            if not os.path.exists(reg_path):
                continue
            try:
                with open(reg_path, "r", encoding="utf-8") as f:
                    registry = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            for pkg_id in registry.get("packages", {}).keys():
                result.setdefault(pkg_id, []).append(entry.name)
        return result

    def _on_card_unpublish(self, pkg_id, registry_name):
        """Handle the unpublish action triggered from a card badge menu."""
        if not self._publisher or not self._config:
            return

        target = None
        for entry in self._config.registries:
            if entry.is_remote:
                continue
            if entry.name == registry_name:
                target = entry
                break
        if target is None:
            QtWidgets.QMessageBox.warning(
                self, t("unpublish_error"),
                "Registry '{}' not found.".format(registry_name),
            )
            return

        # Prefer the installed display_name when we have it; otherwise fall
        # back to whatever the registry knows.
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}
        display = installed.get(pkg_id, {}).get("display_name")
        if not display:
            packages = self._registry_client.get_packages() if self._registry_client else {}
            display = packages.get(pkg_id, {}).get("display_name", pkg_id)

        reply = QtWidgets.QMessageBox.question(
            self, t("unpublish"),
            t("confirm_unpublish", display, registry_name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        self._on_unpublish(pkg_id, target)

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

    def _show_history_for(self, pkg_id):
        """Open the version history dialog for a published package.

        Used from the Edit dialog flow, where the click target is the
        installed-side data (no `versions` map). We pull the registry
        snapshot via the registry client and reuse the same dialog as
        the detail panel.
        """
        if not self._registry_client:
            return
        packages = self._registry_client.get_packages()
        pkg_data = packages.get(pkg_id)
        if not pkg_data:
            QtWidgets.QMessageBox.information(
                self, "Carton", t("history_no_registry_data"),
            )
            return
        installed = self._install_manager.get_installed_packages()
        installed_ver = installed.get(pkg_id, {}).get("version")
        from carton.ui.version_history_dialog import VersionHistoryDialog
        dlg = VersionHistoryDialog(pkg_id, pkg_data, installed_ver, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            chosen = dlg.chosen_version()
            if chosen:
                self._on_rollback(pkg_id, chosen)

    def _on_rollback(self, pkg_id, version):
        """Install a specific older version and pin it."""
        self._on_install(pkg_id, version=version, pinned=True)
        # Refresh the detail panel so the new installed version + pin
        # badge are visible without backing out.
        if self._registry_client:
            packages = self._registry_client.get_packages()
            pkg_data = packages.get(pkg_id)
            if pkg_data:
                installed = self._install_manager.get_installed_packages()
                self._detail.show_package(
                    pkg_id, pkg_data,
                    installed_version=installed.get(pkg_id, {}).get("version"),
                    icon_path=self._resolve_icon_path(pkg_data),
                )

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
        # Note: we intentionally do NOT uninstall the old version first.
        # install_package() performs a transactional replace with rollback,
        # so if the new version fails to download/extract/install, the old
        # version stays intact rather than leaving the user with nothing.
        self._on_install(pkg_id)

    def _check_self_update(self, force=False):
        """Poll GitHub for a newer Carton release and update the banner.

        Respects ``config.auto_check_updates``. Pass ``force=True`` to
        bypass the setting (used by the manual "Check now" button).

        The GitHub probe runs on a background thread so a slow or
        unreachable network never blocks the UI. The banner is updated
        from the worker's finished signal.
        """
        if not self._self_updater:
            return

        # Pending staged updates are a pure local file check — do this
        # synchronously so the banner appears immediately on startup.
        if self._self_updater.has_pending_update():
            ver = self._self_updater.get_pending_version()
            self._update_banner_label.setText(t("update_pending", ver))
            self._update_banner_btn.setVisible(False)
            self._update_banner.setVisible(True)
            return

        if not force and self._config and not self._config.auto_check_updates:
            # Auto-check disabled and nothing staged — keep the banner
            # hidden and skip the network entirely.
            self._update_banner.setVisible(False)
            return

        # Don't stack multiple in-flight checks if the user mashes refresh.
        if self._update_check_worker and self._update_check_worker.isRunning():
            return

        self._update_banner.setVisible(False)
        self._update_check_worker = _SelfUpdateCheckWorker(
            self._self_updater, parent=self,
        )
        self._update_check_worker.finished_signal.connect(
            self._on_self_update_check_done
        )
        self._update_check_worker.start()

    def _on_self_update_check_done(self, result, error):
        """Slot for _SelfUpdateCheckWorker. Runs on the UI thread."""
        if error or not result:
            # Silent on failure: the banner just stays hidden. The user
            # can still click "Check for updates now" in Settings to get
            # an explicit error message.
            return
        self._pending_self_update = result  # (version, download_url)
        self._update_banner_label.setText(t("update_available", result[0]))
        self._update_banner_btn.setVisible(True)
        self._update_banner.setVisible(True)

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

    def _on_install(self, pkg_id, version=None, pinned=False):
        """Install a package. Optionally a specific version and/or pin it."""
        if not self._downloader or not self._install_manager:
            return
        packages = self._registry_client.get_packages() if self._registry_client else {}
        pkg_data = packages.get(pkg_id)
        if not pkg_data:
            return

        self._set_install_button_state(pkg_id, busy=True)
        QtWidgets.QApplication.processEvents()

        pkg_name = pkg_data.get("name", "")
        target_version = version or pkg_data.get("latest_version", "")
        version_info = pkg_data.get("versions", {}).get(target_version, {})

        try:
            url = version_info.get("download_url")
            if not url:
                raise RuntimeError(t("no_download_url"))

            # Strict verify: refuse to install anything from a registry
            # entry that doesn't carry a sha256.
            if self._config and self._config.strict_verify:
                if not version_info.get("sha256"):
                    raise RuntimeError(t("install_strict_no_sha256"))

            dest = os.path.join(
                self._install_manager._config.staging_dir,
                "{}-{}.zip".format(pkg_name, target_version),
            )
            self._downloader.download(
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
                "display_name": pkg_data.get("display_name", pkg_name),
                "entry_point": {},
                "sha256": version_info.get("sha256", ""),
                "pinned": bool(pinned),
            }
            self._install_manager.install_package(dest, meta)

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
                # Maya modules without an explicit launch command have no
                # visible feedback (userSetup.py runs deferred), so show a
                # short confirmation so the click doesn't feel broken.
                if (pkg_data.get("type") == "maya_module"
                        and not (entry_point.get("command")
                                 or entry_point.get("module"))):
                    QtWidgets.QMessageBox.information(
                        self, t("activate"), t("activate_done"),
                    )
                return
            if entry_point.get("type") == "exec" and self._script_manager:
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
                            self._install_manager._config.install_dir,
                            rel, exec_file,
                        )
                    else:
                        exec_data["local_path"] = os.path.join(
                            self._install_manager._config.packages_dir,
                            pkg_data.get("name", ""), exec_file,
                        )
                self._script_manager.launch(exec_data)
            else:
                from carton.core.handlers import get_handler
                handler = get_handler(pkg_data.get("type", "python_package"))
                handler.launch(pkg_data)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, t("launch_error"), str(e))

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
