"""Carton main window."""

import json
import os
from collections import OrderedDict

from carton.compat_urllib import urlopen, Request, URLError, urljoin
from carton.core.display_name_resolver import resolve_display_name
from carton.core.install_state import is_my_tools, is_pure_local
from carton.ui._namespace_grouping import (
    arrow_glyph,
    group_by_namespace,
    toggle_collapsed,
)
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
      2. If ``icon`` is the literal ``"@auto"``, fall back to ``<name>.png``.
      3. Otherwise return None.
    """
    icon_value = pkg_data.get("icon", "")
    if isinstance(icon_value, str) and icon_value.endswith((".png", ".jpg", ".svg")):
        return os.path.basename(icon_value)
    if icon_value == "@auto":
        name = pkg_data.get("name", "")
        if name:
            return "{}.png".format(name)
    return None


class _ClickableLabel(QtWidgets.QLabel):
    """QLabel that emits ``clicked`` on left mouse press.

    Used for tiny icon-style controls (e.g. the profile gear button)
    where Qt's button widgets in Maya unconditionally draw an outer
    frame that bleeds Maya's palette colours through stylesheets.
    """

    clicked = QtCore.Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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
    """Dialog to choose a publish target registry.

    Accepts both local and remote entries. Remote rows annotate the mirror
    mapping so the user can see at a glance which local registry the
    remote will actually write to.
    """

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("publish"))
        self.setMinimumWidth(360)
        self._result_registry = None
        self._config = config

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        registries = list(config.registries)

        # Dropdown for existing registries (local + remote, annotated)
        if registries:
            label = QtWidgets.QLabel(t("publish_select_registry"))
            label.setStyleSheet("font-weight: 600;")
            layout.addWidget(label)

            self._combo = QtWidgets.QComboBox()
            for r in registries:
                label_text, tooltip = self._describe_target(r)
                self._combo.addItem(label_text, r)
                idx = self._combo.count() - 1
                if tooltip:
                    self._combo.setItemData(idx, tooltip, Qt.ToolTipRole)
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

    def _describe_target(self, entry):
        """Return ``(label, tooltip)`` for a registry row in the combo."""
        if not entry.is_remote:
            return entry.name, entry.path
        mirror = None
        if entry.registry_id:
            mirror = self._config.find_local_mirror(entry.registry_id)
        if mirror is not None:
            label = "{} → {}".format(entry.name, mirror.name)
            return label, t("publish_mirrors_to", mirror.name, mirror.path)
        label = "{}  ({})".format(entry.name, t("publish_no_mirror"))
        return label, t("publish_no_mirror_hint")



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

        # Section caption style — small uppercase tracking, used by every
        # sidebar section so the visual rhythm comes from typography +
        # whitespace, not from hairlines.
        self._sidebar_caption_css = (
            "color: {c}; font-size: 10px; font-weight: 800;"
            " letter-spacing: 2px; padding: 4px 8px 4px 8px;"
            " background: transparent;"
        ).format(c=theme.TEXT_PRIMARY)

        # ---- Page 0: Sidebar + Package list ----
        list_page = QtWidgets.QWidget()
        page_layout = QtWidgets.QHBoxLayout(list_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(self._build_sidebar())
        page_layout.addWidget(self._build_content_area())
        self._stack.addWidget(list_page)

        # ---- Page 1: Detail ----
        self._stack.addWidget(self._build_detail_page())

        self._current_tab = "installed"
        self._sidebar_selection = None  # Will be set on refresh

    # ---- _setup_ui helpers ----------------------------------------------

    def _make_sidebar_caption_row(self, text, collapsible_target=None):
        """Caption label + dashed rule on its right.

        If ``collapsible_target`` is given, the caption becomes a clickable
        button that toggles the target widget's visibility and shows a
        chevron next to the text.
        """
        caption_css = self._sidebar_caption_css
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

    def _build_sidebar(self):
        sidebar = QtWidgets.QWidget()
        sidebar.setFixedWidth(180)
        sidebar.setStyleSheet("QWidget {{ background: {}; }}".format(theme.BG_SIDEBAR))
        layout = QtWidgets.QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 14, 10, 10)
        layout.setSpacing(0)

        self._build_sidebar_profile_section(layout)
        layout.addSpacing(16)
        self._build_sidebar_registry_section(layout)
        layout.addSpacing(16)
        self._build_sidebar_mytools_section(layout)
        layout.addStretch(1)
        self._build_sidebar_footer(layout)
        return sidebar

    def _build_sidebar_profile_section(self, parent_layout):
        profile_container = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(profile_container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self._profile_combo = QtWidgets.QComboBox()
        self._profile_combo.setStyleSheet(theme.combobox_style())
        self._profile_combo.currentIndexChanged.connect(self._on_profile_combo_changed)
        row.addWidget(self._profile_combo, stretch=1)

        manage_btn = _ClickableLabel("\u2699")
        manage_btn.setToolTip(t("profile_manage"))
        manage_btn.setCursor(Qt.PointingHandCursor)
        manage_btn.setFixedSize(26, 26)
        manage_btn.setAlignment(Qt.AlignCenter)
        manage_btn.setStyleSheet(
            "QLabel {{ background: {bg2}; border: 1px solid {border};"
            "  border-radius: 4px; color: {muted}; font-size: 14px; }}"
            "QLabel:hover {{ color: {text}; border: 1px solid {border_h};"
            "  background: {hover}; }}".format(
                bg2=theme.BG_SECONDARY, border=theme.BORDER,
                border_h=theme.BORDER_HOVER, muted=theme.TEXT_MUTED,
                text=theme.TEXT_PRIMARY, hover=theme.BG_HOVER)
        )
        manage_btn.clicked.connect(self._open_profile_manager)
        row.addWidget(manage_btn)

        parent_layout.addLayout(self._make_sidebar_caption_row(
            t("profile_label").upper(), collapsible_target=profile_container,
        ))
        parent_layout.addWidget(profile_container)

    def _build_sidebar_registry_section(self, parent_layout):
        self._registry_list = QtWidgets.QListWidget()
        self._registry_list.setStyleSheet(theme.sidebar_list_style())
        self._registry_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._registry_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._registry_list.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        self._registry_list.currentRowChanged.connect(self._on_registry_row_changed)
        parent_layout.addLayout(self._make_sidebar_caption_row(
            t("sidebar_library").upper(), collapsible_target=self._registry_list,
        ))
        parent_layout.addWidget(self._registry_list)

    def _build_sidebar_mytools_section(self, parent_layout):
        self._mytools_list = QtWidgets.QListWidget()
        self._mytools_list.setStyleSheet(theme.sidebar_list_style())
        self._mytools_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._mytools_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._mytools_list.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        self._mytools_list.currentRowChanged.connect(self._on_mytools_row_changed)
        parent_layout.addLayout(self._make_sidebar_caption_row(
            t("my_tools").upper(), collapsible_target=self._mytools_list,
        ))
        parent_layout.addWidget(self._mytools_list)

    def _build_sidebar_footer(self, parent_layout):
        parent_layout.addSpacing(8)
        settings_btn = QtWidgets.QPushButton(
            "⚙  " + t("settings_title").split("—")[-1].strip()
        )
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
        parent_layout.addWidget(settings_btn)

    def _build_content_area(self):
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        self._build_update_banner(layout)
        self._build_search_row(layout)
        self._build_toolbar(layout)
        self._build_card_list(layout)
        return content

    def _build_update_banner(self, parent_layout):
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
        parent_layout.addWidget(self._update_banner)

    def _build_search_row(self, parent_layout):
        row = QtWidgets.QHBoxLayout()
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText(t("search_placeholder"))
        self._search.textChanged.connect(self._filter_cards)
        row.addWidget(self._search)

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
        row.addWidget(refresh_btn)
        parent_layout.addLayout(row)

    def _build_toolbar(self, parent_layout):
        """Tabs + register button. Visibility depends on sidebar selection."""
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

        parent_layout.addLayout(toolbar)

    def _build_card_list(self, parent_layout):
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
        parent_layout.addWidget(scroll)

    def _build_detail_page(self):
        self._detail = PackageDetailPanel()
        self._detail.back_requested.connect(lambda: self._stack.setCurrentIndex(0))
        self._detail.install_requested.connect(self._on_install)
        self._detail.rollback_requested.connect(self._on_rollback)
        self._detail.uninstall_requested.connect(self._on_uninstall)
        self._detail.launch_requested.connect(self._on_launch)
        return self._detail

    # ---- public API ----

    def deferred_init(self):
        QtCore.QTimer.singleShot(0, self._do_deferred_init)

    def _do_deferred_init(self):
        self.refresh()
        self._loading_label.setVisible(False)

    def _create_new_registry(self, paired_remote=None):
        """Create a new empty registry directory. Returns the RegistryEntry or None.

        If ``paired_remote`` is given, the new registry inherits its
        ``registry_id`` so that publishes to the remote route here via
        :meth:`Config.find_local_mirror`.
        """
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
        from carton.core.registry_id import new_registry_id
        from carton.ui._registry_pairing import probe_remote_registry_id

        reg_path = os.path.join(folder, "registry.json")
        if paired_remote is not None:
            rid = paired_remote.registry_id or probe_remote_registry_id(paired_remote.path)
            if rid:
                paired_remote.registry_id = rid
            else:
                rid = new_registry_id()
                # Remote doesn't expose an id — the user will need to
                # re-upload this registry.json before the remote can
                # resolve back.
        else:
            rid = new_registry_id()

        if not os.path.exists(reg_path):
            os.makedirs(folder, exist_ok=True)
            with open(reg_path, "w", encoding="utf-8") as f:
                json.dump({
                    "schema_version": "3.1",
                    "registry_id": rid,
                    "packages": {},
                }, f, indent=2, ensure_ascii=False)
            os.makedirs(os.path.join(folder, "packages"), exist_ok=True)
        else:
            # Folder already has a registry.json — stamp if missing so the
            # pairing still works.
            from carton.core.registry_id import stamp_registry_id
            try:
                with open(reg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                data = {"schema_version": "3.1", "packages": {}}
            # If we're pairing with a remote and the existing file has a
            # different id, prefer the remote's (so the pair works).
            current = data.get("registry_id", "")
            if paired_remote is not None and rid and current != rid:
                data["registry_id"] = rid
                data["schema_version"] = "3.1"
                with open(reg_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                stamp_registry_id(data)
                rid = data["registry_id"]
                data.setdefault("schema_version", "3.1")
                with open(reg_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

        self._config.add_registry(name, reg_path, registry_id=rid)
        self._config.save()
        # Return the newly added entry
        return self._config.registries[-1]

    def _add_existing_registry(self, paired_remote=None):
        """Browse for an existing registry.json. Returns the RegistryEntry or None."""
        from carton.ui._registry_pairing import (
            DuplicateRegistryChoice,
            find_duplicate_entry,
            read_local_registry_id,
            resolve_duplicate_registry,
            stamp_local_registry_with_prompt,
        )

        path = QtWidgets.QFileDialog.getOpenFileName(
            self, t("settings_select_registry"), "",
            "Registry (registry.json);;JSON (*.json)",
        )[0]
        if not path:
            return None

        rid, data = read_local_registry_id(path)
        if not rid and data is not None:
            rid = stamp_local_registry_with_prompt(self, path, data)

        # Duplicate detection — skip the paired remote itself, because a
        # pairing flow is supposed to land on the same UUID (that's the
        # whole point). Also skip the same normalised path.
        existing = find_duplicate_entry(
            self._config.registries, rid, path,
            ignore=[paired_remote] if paired_remote is not None else None,
        )
        if existing is not None:
            choice = resolve_duplicate_registry(self, existing)
            if choice == DuplicateRegistryChoice.CANCEL:
                return None
            if choice == DuplicateRegistryChoice.USE_EXISTING:
                if paired_remote is not None and not paired_remote.registry_id:
                    paired_remote.registry_id = rid
                    self._config.save()
                return existing

        base = os.path.basename(os.path.dirname(path))
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Registry Name",
            t("setup_registry_name"),
            text=base,
        )
        if not ok or not name:
            return None

        self._config.add_registry(name, path, registry_id=rid)
        if paired_remote is not None and rid and not paired_remote.registry_id:
            paired_remote.registry_id = rid
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
        from carton.core.profile import InstallerProfile
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        names = profile_store.ordered_profiles(self._config.profile_order)
        # Recovery: if nothing is on disk (fresh install or accidental
        # state loss), materialise the default profile from the current
        # Config snapshot so the user always has at least one entry.
        if not names:
            try:
                profile_store.save_profile(
                    profile_store.DEFAULT_PROFILE_NAME,
                    InstallerProfile.from_config(self._config),
                )
                self._config.active_profile = profile_store.DEFAULT_PROFILE_NAME
                self._config.save()
                names = profile_store.ordered_profiles(self._config.profile_order)
            except Exception:
                pass
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

    def _resolve_registry_selection(self, selection):
        """Map a sidebar selection (registry name) to its config entry.

        Returns the entry, or None if the selection doesn't match any
        registry (e.g. ``self._MYTOOLS_KEY`` or a stale value).
        """
        if not selection or not self._config:
            return None
        for entry in self._config.registries:
            if entry.name == selection:
                return entry
        return None

    def _pkg_belongs_to_entry(self, pkg_data, entry):
        """True if ``pkg_data`` belongs to ``entry`` (id-aware, name-fallback).

        Packages get attributed to whichever registry loaded first when two
        share a ``registry_id`` (local mirror + paired remote). A naive
        name match would miss them on the *other* side; matching by
        ``registry_id`` keeps the sidebar selection honest regardless of
        load order. Falls back to the alias name when neither side has a
        UUID yet (legacy/unstamped registries).
        """
        if entry is None:
            return False
        entry_rid = getattr(entry, "registry_id", "")
        pkg_rid = pkg_data.get("_registry_id", "")
        if entry_rid and pkg_rid and entry_rid == pkg_rid:
            return True
        return pkg_data.get("_registry_name", "") == entry.name

    def _rebuild_sidebar(self):
        """Rebuild sidebar items from config registries + My Tools."""
        prev = self._sidebar_selection
        for lst in (self._registry_list, self._mytools_list):
            lst.blockSignals(True)
            lst.clear()

        packages = self._registry_client.get_packages() if self._registry_client else {}
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}

        # Count packages two ways: by alias name (legacy / unstamped
        # registries) and by registry_id (canonical, survives the local↔
        # remote mirror dedup that drops one side's _registry_name).
        reg_counts_by_name = {}
        reg_counts_by_id = {}
        for pkg_data in packages.values():
            rn = pkg_data.get("_registry_name", "")
            reg_counts_by_name[rn] = reg_counts_by_name.get(rn, 0) + 1
            rid = pkg_data.get("_registry_id", "")
            if rid:
                reg_counts_by_id[rid] = reg_counts_by_id.get(rid, 0) + 1

        # Hide local mirrors from the sidebar when a remote entry shares
        # their registry_id — the remote is the canonical "consumer"
        # face, the local is just the publish-side write target. Both
        # remain accessible from Settings → Registries for management.
        remote_ids = {
            e.registry_id for e in (self._config.registries if self._config else [])
            if e.is_remote and e.registry_id
        }

        # Registries
        if self._config:
            for entry in self._config.registries:
                if (not entry.is_remote
                        and entry.registry_id
                        and entry.registry_id in remote_ids):
                    continue
                if entry.registry_id and entry.registry_id in reg_counts_by_id:
                    count = reg_counts_by_id[entry.registry_id]
                else:
                    count = reg_counts_by_name.get(entry.name, 0)
                item = QtWidgets.QListWidgetItem("{} ({})".format(entry.name, count))
                item.setData(Qt.UserRole, entry.name)
                self._registry_list.addItem(item)

        # My Tools — All + namespace children
        my_pkgs = [p for p in installed.values() if is_my_tools(p)]
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
            sel_entry = self._resolve_registry_selection(self._sidebar_selection)
            has_installed = any(
                pkg_id in installed
                for pkg_id, pkg_data in packages.items()
                if self._pkg_belongs_to_entry(pkg_data, sel_entry)
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
        self._stop_icon_fetcher()
        self._card_map = {}
        self._clear_card_layout()

        selection = self._sidebar_selection
        installed = (
            self._install_manager.get_installed_packages()
            if self._install_manager else {}
        )

        if self._is_mytools_selection(selection):
            visible_items = self._collect_mytools_items(installed, selection)
        else:
            packages = (
                self._registry_client.get_packages()
                if self._registry_client else {}
            )
            visible_items = self._collect_registry_items(packages, installed, selection)

        # pkg_id -> [writable local registry names], for "Published-to" badges.
        # Built once per rebuild instead of per-card.
        published_map = self._build_published_map()

        is_my_tools_view = (selection == self._MYTOOLS_KEY)  # only "All", not ns children
        icon_fetch_tasks = []
        ns_groups = {}  # ns_key -> (header_btn, [card widgets])

        if is_my_tools_view:
            for ns, group_items in group_by_namespace(visible_items):
                header = self._create_mytools_group_header(ns)
                ns_groups[ns] = (header, [])
                self._insert_card_widget(header)
                for pkg_id, pkg_data in group_items:
                    card = self._create_package_card(
                        pkg_id, pkg_data, selection, published_map,
                        icon_fetch_tasks,
                    )
                    self._insert_card_widget(card)
                    ns_groups[ns][1].append(card)
        else:
            for pkg_id, pkg_data in visible_items:
                card = self._create_package_card(
                    pkg_id, pkg_data, selection, published_map,
                    icon_fetch_tasks,
                )
                self._insert_card_widget(card)

        # Apply initial collapsed state for My Tools groups
        self._mytools_groups = ns_groups
        for ns_key, (_hdr, cards) in ns_groups.items():
            if ns_key in self._mytools_collapsed:
                for c in cards:
                    c.setVisible(False)

        self._start_icon_fetcher(icon_fetch_tasks)

    # ---- _rebuild_cards helpers ------------------------------------------

    def _stop_icon_fetcher(self):
        """Stop any in-flight icon fetcher from a previous rebuild."""
        if self._icon_fetcher and self._icon_fetcher.isRunning():
            self._icon_fetcher.quit()
            self._icon_fetcher.wait()
            self._icon_fetcher = None

    def _clear_card_layout(self):
        """Remove all cards from the layout, leaving the trailing stretch."""
        while self._card_layout.count() > 1:
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _insert_card_widget(self, widget):
        """Insert a widget just before the trailing stretch in the card layout."""
        idx = self._card_layout.count() - 1
        self._card_layout.insertWidget(idx, widget)

    def _start_icon_fetcher(self, tasks):
        """Kick off background icon download for uncached remote icons."""
        if not tasks:
            return
        self._icon_fetcher = _IconFetcher(tasks, self._config, parent=self)
        self._icon_fetcher.icon_ready.connect(self._on_icon_ready)
        self._icon_fetcher.start()

    def _collect_mytools_items(self, installed, selection):
        """Return ``[(pkg_id, view_data)]`` for the My Tools view, sorted by ns."""
        ns_filter = self._mytools_ns_filter(selection)
        registry_packages = (
            self._registry_client.get_packages() if self._registry_client else {}
        )
        items = []
        for pkg_id, pkg_data in installed.items():
            if not is_my_tools(pkg_data):
                continue
            if ns_filter is not None:
                pkg_ns = (pkg_data.get("namespace") or "").lower()
                if pkg_ns != ns_filter:
                    continue
            item = dict(pkg_data)
            item["_installed_ver"] = pkg_data.get("version")
            item["_local_script"] = True
            # registry SoT for display_name on registry-side entries; My Tools
            # rows already carry their own display_name.
            item["display_name"] = resolve_display_name(
                pkg_id, pkg_data, registry_packages.get(pkg_id),
            )
            items.append((pkg_id, item))
        items.sort(key=lambda x: (
            (x[1].get("namespace") or "~").lower(),
            x[1].get("display_name", ""),
        ))
        return items

    def _collect_registry_items(self, packages, installed, selection):
        """Return ``[(pkg_id, view_data)]`` for the selected registry view."""
        sel_entry = self._resolve_registry_selection(selection)
        items = []
        for pkg_id, pkg_data in packages.items():
            if not self._pkg_belongs_to_entry(pkg_data, sel_entry):
                continue
            item = dict(pkg_data)
            # A demoted (uninstalled-from-registry) entry stays in
            # installed.json as source="local" so it remains in My Tools,
            # but the registry view should show it as not-installed so
            # the user can re-install if they want.
            inst_entry = installed.get(pkg_id, {})
            is_installed = (
                pkg_id in installed
                and not is_pure_local(inst_entry)
            )
            if is_installed:
                inst = installed[pkg_id]
                item["_installed_ver"] = inst.get("version")
                # Verified badge: read sha256 from the registry's
                # version_entry for the version we actually installed.
                # installed.json no longer carries a sha256 of its own.
                inst_ver = inst.get("version", "")
                ver_info = pkg_data.get("versions", {}).get(inst_ver, {})
                if ver_info.get("sha256"):
                    item["sha256"] = ver_info["sha256"]
                if inst.get("pinned"):
                    item["pinned"] = True
                if is_my_tools(inst):
                    item["_local_script"] = True
            if self._current_tab == "installed" and not is_installed:
                continue
            items.append((pkg_id, item))
        items.sort(key=lambda x: x[1].get("display_name", ""))
        return items

    def _create_mytools_group_header(self, ns):
        """Build the collapsible header button for a My Tools namespace group."""
        label_text = ns if ns else t("my_tools_no_namespace")
        collapsed = ns in self._mytools_collapsed
        arrow = arrow_glyph(not collapsed)
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
        header.clicked.connect(
            lambda _checked=False, k=ns: self._toggle_mytools_group(k)
        )
        return header

    def _create_package_card(self, pkg_id, pkg_data, selection,
                              published_map, icon_fetch_tasks):
        """Build a single PackageCard and register it in ``_card_map``.

        Side effect: appends ``(pkg_id, base_dir, icon_filename)`` to
        ``icon_fetch_tasks`` for any remote icon that needs to be fetched
        in the background.
        """
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
            installed_version=pkg_data.get("_installed_ver"),
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
        if in_my_tools_view:
            card.mousePressEvent = lambda e, pid=pkg_id: self._show_edit(pid)
        else:
            card.mousePressEvent = lambda e, pid=pkg_id: self._show_detail(pid)
        return card

    def _toggle_mytools_group(self, ns_key):
        group = self._mytools_groups.get(ns_key)
        if not group:
            return
        header, cards = group
        visible = toggle_collapsed(self._mytools_collapsed, ns_key)
        for c in cards:
            c.setVisible(visible)
        # Update arrow in header text (first 1 char + 2 spaces + label)
        text = header.text()
        if len(text) >= 3:
            header.setText(arrow_glyph(visible) + text[1:])

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
        pkg_data = self._install_manager.get_installed_packages().get(pkg_id, {})
        if not pkg_data:
            return

        # Check which registries have this package published
        published_regs = []
        if self._publisher:
            published_regs = self._publisher.find_published_registries(pkg_id)

        result = EditDialog.prompt(
            pkg_id, pkg_data,
            published_registries=published_regs, parent=self,
        )
        if not result:
            return

        action = result["action"]
        if action == "history":
            self._show_history_for(pkg_id)
        elif action == "unpublish":
            self._on_unpublish(pkg_id, result["registry"])
        elif action == "remove":
            if self._script_manager:
                self._script_manager.unregister(pkg_id)
            self._rebuild_sidebar()
            self._rebuild_cards()
        elif action == "save":
            self._apply_edit_save(pkg_id, pkg_data, result, published_regs)

    def _apply_edit_save(self, pkg_id, pkg_data, result, published_regs):
        """Persist an EditDialog "save" result and refresh the views."""
        fields = {
            "display_name": result["display_name"],
            "version": result["version"],
            "author": result["author"],
            "icon": result["icon"],
            "homepage": result["homepage"],
            "description": result["description"],
            "entry_point": result["entry_point"],
            "include_compiled": result.get("include_compiled", False),
        }

        new_pkg_id = self._resolve_edit_namespace_change(
            pkg_id, pkg_data, result, published_regs, fields,
        )
        if new_pkg_id is None:
            return  # Validation failed; user already saw an error dialog

        if new_pkg_id != pkg_id:
            self._install_manager.rekey_package(pkg_id, new_pkg_id, fields)
        else:
            self._install_manager.update_package_fields(pkg_id, fields)
        # Sidebar counts and namespace children depend on the current
        # installed.json snapshot — refresh both views so renames /
        # namespace changes show up immediately.
        self._rebuild_sidebar()
        self._rebuild_cards()

    def _resolve_edit_namespace_change(self, pkg_id, pkg_data, result,
                                        published_regs, fields):
        """Validate a namespace change from the edit dialog.

        Mutates ``fields`` in place to add ``namespace`` when the change is
        accepted. Returns the (possibly new) pkg_id, or None if validation
        failed (in which case an error dialog has already been shown).
        Namespace changes are ignored when the package is already published
        somewhere — the on-disk identity is locked.
        """
        new_ns = result.get("namespace", "")
        old_ns = pkg_data.get("namespace", "")
        if new_ns == old_ns or published_regs:
            return pkg_id

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
                return None

        fields["namespace"] = new_ns
        name = pkg_data.get("name", "")
        return "{}/{}".format(new_ns, name) if new_ns else name

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

        pkg_data = self._install_manager.get_installed_packages().get(pkg_id)
        if not pkg_data:
            return

        target_registry = self._pick_publish_target_registry()
        if not target_registry:
            return

        if not self._confirm_home_registry_mismatch(pkg_data, target_registry):
            return

        namespace = self._ensure_publish_namespace(pkg_id, pkg_data)
        if not namespace:
            return

        confirm_result = self._confirm_publish_details(pkg_data, target_registry)
        if not confirm_result:
            return
        release_notes, embed_source_path = confirm_result

        self._run_publish(
            pkg_id, pkg_data, target_registry,
            namespace, release_notes, embed_source_path,
        )

    def _pick_publish_target_registry(self):
        """Show the publish-target dialog and return a registry, or None."""
        dlg = _PublishTargetDialog(self._config, parent=self)
        result = dlg.exec_()
        if result == 1:  # Selected from dropdown
            return dlg.selected_registry
        if result == 2:  # Create new
            return self._create_new_registry()
        if result == 3:  # Add existing
            return self._add_existing_registry()
        return None  # Cancelled / unknown

    def _confirm_home_registry_mismatch(self, pkg_data, target_registry):
        """Warn if publishing to a different registry than the home one.

        Compares by ``registry_id`` when both sides have one so that a
        registry known under different names on different machines still
        passes without a prompt. Falls back to name equality for legacy
        entries that pre-date UUID stamping.

        Returns True to proceed, False if the user cancelled.
        """
        home_meta = pkg_data.get("home_registry") or {}
        home_name = home_meta.get("name", "")
        home_id = home_meta.get("registry_id", "")
        target_id = getattr(target_registry, "registry_id", "")

        if home_id and target_id:
            if home_id == target_id:
                return True
        elif home_name and home_name == target_registry.name:
            return True
        elif not home_name and not home_id:
            return True

        reply = QtWidgets.QMessageBox.question(
            self, t("publish"),
            t("publish_home_registry_mismatch",
              home_name or home_id, target_registry.name),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        return reply == QtWidgets.QMessageBox.Yes

    def _ensure_publish_namespace(self, pkg_id, pkg_data):
        """Return the package namespace, prompting and persisting if missing.

        Returns None if the user cancelled or supplied an invalid value.
        """
        namespace = pkg_data.get("namespace", "")
        if namespace:
            return namespace
        from carton.core.identity import slugify_namespace
        ns, ok = QtWidgets.QInputDialog.getText(
            self, t("publish"), t("publish_namespace_prompt"),
        )
        if not ok or not ns.strip():
            return None
        namespace = slugify_namespace(ns)
        if not namespace:
            return None
        # Persist immediately so subsequent publishes don't re-ask
        self._install_manager.update_package_fields(
            pkg_id, {"namespace": namespace}
        )
        return namespace

    def _confirm_publish_details(self, pkg_data, target_registry):
        """Show the confirm dialog. Returns ``(release_notes, embed_source_path)``
        or None if cancelled.
        """
        from carton.ui.publish_confirm_dialog import PublishConfirmDialog
        display = pkg_data.get("display_name", "")
        local_version = pkg_data.get("version", "0.0.0")
        confirm = PublishConfirmDialog(
            display, local_version, target_registry.name, parent=self,
        )
        if confirm.exec_() != QtWidgets.QDialog.Accepted:
            return None
        return confirm.release_notes(), confirm.embed_source_path()

    def _run_publish(self, pkg_id, pkg_data, target_registry,
                     namespace, release_notes, embed_source_path):
        """Execute the publish call and reflect the result in installed.json."""
        from carton.core.publisher import RemoteMirrorMissingError

        self._set_publish_button_state(pkg_id, busy=True)
        QtWidgets.QApplication.processEvents()

        try:
            result = self._publisher.publish(
                pkg_data, target_registry, namespace=namespace,
                release_notes=release_notes,
                embed_source_path=embed_source_path,
            )
        except RemoteMirrorMissingError as e:
            self._set_publish_button_state(pkg_id, busy=False)
            self._handle_missing_mirror(
                pkg_id, pkg_data, e, namespace,
                release_notes, embed_source_path,
            )
            return
        except Exception as e:
            self._set_publish_button_state(pkg_id, busy=False)
            self._show_publish_error(e)
            return

        # Re-key the installed entry under the canonical namespace/name.
        # The local path we actually wrote to may differ from the user's
        # selection (remote → mirror), so resolve the name via the result.
        written_name = result.get("published_via") or target_registry.name
        written_entry = self._find_registry_by_name(written_name) or target_registry
        fields = {
            "namespace": result["namespace"],
            "name": result["name"],
        }
        if not pkg_data.get("home_registry"):
            fields["home_registry"] = written_entry.to_home_meta()
        self._install_manager.rekey_package(pkg_id, result["id"], fields)

        display = pkg_data.get("display_name", pkg_id)
        warnings = result.get("warnings") or []
        msg = t("publish_success", display)
        via = result.get("published_via")
        if via:
            msg += "\n\n" + t("publish_remote_sync_reminder", via)
        if warnings:
            msg += "\n\nWarnings:\n  - " + "\n  - ".join(warnings)
        QtWidgets.QMessageBox.information(self, t("publish"), msg)
        self.refresh()

    def _find_registry_by_name(self, name):
        for entry in self._config.registries:
            if entry.name == name:
                return entry
        return None

    def _handle_missing_mirror(self, pkg_id, pkg_data, err, namespace,
                               release_notes, embed_source_path):
        """Walk the user through pairing a local mirror with a remote entry.

        ``err.reason`` is one of ``"no_remote_id"`` / ``"no_local_mirror"``
        (see :class:`carton.core.publisher.RemoteMirrorMissingError`).
        """
        remote = err.remote_entry
        if err.reason == "no_remote_id":
            QtWidgets.QMessageBox.warning(
                self, t("publish"),
                t("publish_no_remote_id", remote.name),
            )
            return

        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle(t("publish"))
        box.setText(t("publish_no_mirror_prompt", remote.name))
        create_btn = box.addButton(
            t("publish_create_mirror"), QtWidgets.QMessageBox.AcceptRole,
        )
        pair_btn = box.addButton(
            t("publish_pair_existing"), QtWidgets.QMessageBox.AcceptRole,
        )
        box.addButton(t("cancel"), QtWidgets.QMessageBox.RejectRole)
        box.exec_()
        clicked = box.clickedButton()

        mirror = None
        if clicked is create_btn:
            mirror = self._create_new_registry(paired_remote=remote)
        elif clicked is pair_btn:
            mirror = self._add_existing_registry(paired_remote=remote)

        if mirror is None:
            return
        # Retry publish against the original remote — the publisher will now
        # find the mirror via the shared registry_id.
        self._run_publish(
            pkg_id, pkg_data, remote, namespace,
            release_notes, embed_source_path,
        )

    def _show_publish_error(self, exc):
        """Display a publish-error dialog mapped to a friendly message."""
        from carton.core.publisher import (
            VersionConflictError,
            MissingNamespaceError,
            InvalidPythonPackageLayoutError,
        )
        if isinstance(exc, VersionConflictError):
            msg = t("publish_already_published", exc.version)
        elif isinstance(exc, (MissingNamespaceError, InvalidPythonPackageLayoutError)):
            msg = str(exc)
        else:
            msg = str(exc)
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

        # Resolve display via the standard resolver: registry SoT for
        # registry-side entries, installed.json for My Tools.
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}
        packages = self._registry_client.get_packages() if self._registry_client else {}
        display = resolve_display_name(
            pkg_id, installed.get(pkg_id), packages.get(pkg_id),
        )

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
        packages = self._registry_client.get_packages() if self._registry_client else {}
        display = resolve_display_name(pkg_id, pkg_data, packages.get(pkg_id))

        try:
            self._publisher.unpublish(pkg_id, registry_entry)

            # Demote double-bound entries to pure My Tools — the registry
            # bytes are gone but the user's local registration survives.
            self._install_manager.update_package_fields(
                pkg_id, {"source": "local"}
            )

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
                "pinned": bool(pinned),
                # Resolved absolute icon path so a relinked My Tools
                # entry can render its custom icon without re-fetching.
                "icon_resolved": self._resolve_icon_path(pkg_data) or "",
            }
            self._install_manager.install_package(dest, meta)

            if os.path.exists(dest):
                os.remove(dest)

            # Refresh sidebar too — installs that auto-relink as My
            # Tools entries change the My Tools count and namespace
            # children, and the sidebar wouldn't otherwise notice.
            self._rebuild_sidebar()
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
        from carton.core.entry_point_resolver import resolve_entry_point

        installed = self._install_manager.get_installed_packages()
        pkg_data = installed.get(pkg_id, {})
        # Resolve entry_point: zip's inner package.json is SoT for registry
        # installs; installed.json carries it for My Tools only.
        package_dir = ""
        rel = pkg_data.get("path", "")
        if rel and self._install_manager:
            package_dir = os.path.join(
                self._install_manager._config.install_dir, rel,
            )
        registry_packages = (
            self._registry_client.get_packages() if self._registry_client else {}
        )
        entry_point = resolve_entry_point(
            pkg_data, package_dir=package_dir,
            registry_data=registry_packages.get(pkg_id),
        )
        # Inject the resolved entry_point back into pkg_data so handlers /
        # script_manager that read meta["entry_point"] still get a value.
        pkg_data = dict(pkg_data)
        pkg_data["entry_point"] = entry_point
        try:
            if is_my_tools(pkg_data) and self._script_manager:
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
            self._show_launch_error(e)

    def _show_launch_error(self, exc):
        """Show a launch failure with the full traceback in Show Details.

        Many "Carton launch errors" are actually exceptions from inside
        the tool the user just ran (e.g. ``NoneType object is not
        subscriptable`` from ``cmds.ls(sl=True)[0]`` with no selection).
        Surfacing the traceback makes it obvious whether to investigate
        Carton or the tool itself.
        """
        import traceback
        tb_text = traceback.format_exc()
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(t("launch_error"))
        box.setText(str(exc))
        box.setInformativeText(t("launch_error_hint"))
        box.setDetailedText(tb_text)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        box.exec_()

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
