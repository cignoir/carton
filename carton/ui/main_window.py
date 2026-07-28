"""Carton main window."""

from carton.core.display_name_resolver import resolve_display_name
from carton.core.install_state import is_my_tools, is_pure_local
from carton.ui._catalogue_crud import add_existing_catalogue, create_new_catalogue
from carton.ui._icon_fetch import IconFetcher, resolve_icon_path
from carton.ui._edit_controller import EditController
from carton.ui._install_controller import InstallController
from carton.ui._profile_controller import ProfileController
from carton.ui._publish_controller import PublishController
from carton.ui._self_update_controller import SelfUpdateController
from carton.ui._namespace_grouping import (
    arrow_glyph,
    group_by_namespace,
    toggle_collapsed,
)
from carton.ui._busy import run_with_busy
from carton.ui.compat import QtWidgets, QtCore, Qt
from carton.ui.error_messages import show_error
from carton.ui.i18n import t
from carton.ui import theme
from carton.ui.package_card import PackageCard
from carton.ui.package_detail import PackageDetailPanel
from carton.ui.settings_dialog import SettingsDialog
from carton.ui.add_dialog import AddDialog

_WINDOW_TITLE = "Carton"
_WINDOW_WIDTH = 780
_WINDOW_HEIGHT = 600


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


_STYLE = theme.MAIN_STYLE


# Maya provides MayaQWidgetDockableMixin so a QWidget can be hosted inside a
# workspaceControl — the same dock/tab/float machinery Maya's own panels use.
# Outside Maya (CI, standalone tests) the mixin doesn't exist; in that case we
# fall back to a plain QWidget so the same class still constructs cleanly.
try:
    from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

    class _CartonWindowBase(MayaQWidgetDockableMixin, QtWidgets.QWidget):
        pass
except ImportError:
    class _CartonWindowBase(QtWidgets.QWidget):
        pass


# Stable objectName so Maya re-uses the same workspaceControl across show() calls
# instead of spawning a new floating panel every time.
WINDOW_OBJECT_NAME = "CartonWindow"


class CartonWindow(_CartonWindowBase):
    """Carton package manager main window."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(WINDOW_OBJECT_NAME)
        # Top-level window flag is required so Qt doesn't embed us as a child
        # widget when parent is the Maya main window — the mixin still wraps
        # us in a workspaceControl when show(dockable=True) is called.
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        import carton
        self.setWindowTitle("{} v{}".format(_WINDOW_TITLE, carton.__version__))
        self.setMinimumSize(_WINDOW_WIDTH, _WINDOW_HEIGHT)
        self.setStyleSheet(_STYLE)

        self._catalogue_client = None
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
        # Library view tracks its own collapse state so My Tools and
        # Library can hide the same namespace independently — the user
        # might want mystudio expanded in Library but collapsed in
        # My Tools (or vice versa).
        self._library_collapsed = set()
        self._library_groups = {}
        # Groups and collapse set belonging to whichever view is
        # currently rendered — the inputs _apply_card_visibility resolves
        # against the search query. Empty for flat (per-namespace) views.
        self._active_ns_groups = {}
        self._active_collapsed = set()
        self._update_check_worker = None
        self._refreshing = False
        self._cards_rebuilt_by_sidebar = False
        # Icon fetchers that overran their join budget, kept alive and
        # unparented so they can finish without the window waiting on
        # them (see _stop_icon_fetcher).
        self._detached_fetchers = []

        self._install_ctl = InstallController(self)
        self._publish_ctl = PublishController(self)
        self._self_update_ctl = SelfUpdateController(self)
        self._edit_ctl = EditController(self)
        self._profile_ctl = ProfileController(self)

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
        self._build_sidebar_catalogue_section(layout)
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

    def _build_sidebar_catalogue_section(self, parent_layout):
        self._catalogue_list = QtWidgets.QListWidget()
        self._catalogue_list.setStyleSheet(theme.sidebar_list_style())
        self._catalogue_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._catalogue_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._catalogue_list.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        self._catalogue_list.currentRowChanged.connect(self._on_catalogue_row_changed)
        parent_layout.addLayout(self._make_sidebar_caption_row(
            t("sidebar_library").upper(), collapsible_target=self._catalogue_list,
        ))
        parent_layout.addWidget(self._catalogue_list)

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

    def _create_new_catalogue(self, paired_remote=None):
        return create_new_catalogue(self, paired_remote=paired_remote)

    def _add_existing_catalogue(self, paired_remote=None):
        return add_existing_catalogue(self, paired_remote=paired_remote)

    def set_services(self, catalogue_client, install_manager, downloader,
                     self_updater=None, config=None, script_manager=None,
                     publisher=None):
        self._catalogue_client = catalogue_client
        self._install_manager = install_manager
        self._downloader = downloader
        self._self_updater = self_updater
        self._script_manager = script_manager
        self._publisher = publisher
        self._config = config
        self._rebuild_profile_combo()

    def _rebuild_profile_combo(self):
        self._profile_ctl.rebuild_combo()

    def _on_profile_combo_changed(self, index):
        self._profile_ctl.on_combo_changed(index)

    def _open_profile_manager(self):
        self._profile_ctl.open_manager()

    def refresh(self):
        """Re-read every catalogue and rebuild the views.

        The fetch is the expensive half — one HTTP round trip per remote
        catalogue, each with its own timeout, run in series. On the UI
        thread that is a multi-minute freeze of all of Maya when a
        subscribed host is unreachable, with nothing on screen to say
        why. It runs on a worker instead, behind the shared busy dialog.

        The call still *reads* synchronously: every caller here assumes
        the package dict is current by the time refresh() returns, and a
        signal-based rewrite would push that assumption into a dozen
        call sites for no user-visible gain.
        """
        if not self._catalogue_client:
            return
        # refresh() is reachable from the settings dialog closing, the
        # toolbar button, install/publish completion and deferred init.
        # The worker runs a nested event loop, so without this guard a
        # second refresh can start on top of one already in flight.
        if self._refreshing:
            return
        self._refreshing = True
        try:
            run_with_busy(
                self, self._catalogue_client.fetch, label=t("busy_refreshing"),
            )
        except Exception as e:
            # CatalogueClient already absorbs per-catalogue failures, so
            # reaching here means something broader broke. Show the cards
            # we have rather than leaving the user on a stale view with
            # no explanation.
            show_error(self, e, operation="refresh")
        finally:
            self._refreshing = False
        # _rebuild_sidebar re-selects a row, and when that changes the
        # current row Qt delivers currentRowChanged -> _apply_sidebar_
        # selection -> _rebuild_cards. When the previous selection is
        # restored unchanged, no signal fires and nobody rebuilds. Track
        # which happened instead of unconditionally rebuilding after:
        # every card widget is constructed from scratch here, and the
        # second pass also has to stop and join the icon fetcher the
        # first one just started.
        self._cards_rebuilt_by_sidebar = False
        self._rebuild_sidebar()
        if not self._cards_rebuilt_by_sidebar:
            self._rebuild_cards()
        self._check_self_update()

    _MYTOOLS_KEY = "__my_tools__"
    _MYTOOLS_NS_PREFIX = "__my_tools__:"
    # v5.0: Library sidebar is a namespace tree (All + per-namespace children)
    # rather than a catalogue-per-row list. Package-first means the user
    # asks "which namespace?" more often than "which catalogue?" — catalogue
    # lookup stays available via Settings → Catalogues.
    _LIBRARY_KEY = "__library__"
    _LIBRARY_NS_PREFIX = "__library__:"

    def _is_mytools_selection(self, key):
        return key == self._MYTOOLS_KEY or (
            isinstance(key, str) and key.startswith(self._MYTOOLS_NS_PREFIX)
        )

    def _mytools_ns_filter(self, key):
        """Return the namespace key if selection is a child, else None."""
        if isinstance(key, str) and key.startswith(self._MYTOOLS_NS_PREFIX):
            return key[len(self._MYTOOLS_NS_PREFIX):]
        return None

    def _is_library_selection(self, key):
        return key == self._LIBRARY_KEY or (
            isinstance(key, str) and key.startswith(self._LIBRARY_NS_PREFIX)
        )

    def _library_ns_filter(self, key):
        """Return the namespace filter for a Library selection, or None for 'all'.

        ``None`` is returned both for the Library root (All) and for any
        non-library selection, so callers can ``if ns is None`` to mean
        "show everything in scope".
        """
        if isinstance(key, str) and key.startswith(self._LIBRARY_NS_PREFIX):
            return key[len(self._LIBRARY_NS_PREFIX):]
        return None

    def _rebuild_sidebar(self):
        """Rebuild sidebar items from config registries + My Tools."""
        prev = self._sidebar_selection
        for lst in (self._catalogue_list, self._mytools_list):
            lst.blockSignals(True)
            lst.clear()

        packages = self._catalogue_client.get_packages() if self._catalogue_client else {}
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}

        # Library — All + namespace children. Mirrors the My Tools layout:
        # package-first means the user picks a namespace to browse rather
        # than a catalogue, and same-pkg-id across catalogues is already
        # deduped by CatalogueClient (first-catalogue-wins). Catalogue-
        # level management (Add / Edit / Remove) moved to the Settings
        # dialog since v5.0's Library view is not catalogue-scoped.
        lib_total = len(packages)
        all_item = QtWidgets.QListWidgetItem(
            "{} ({})".format(t("library_all"), lib_total),
        )
        all_item.setData(Qt.UserRole, self._LIBRARY_KEY)
        self._catalogue_list.addItem(all_item)

        lib_ns_counts = {}
        for pkg_data in packages.values():
            ns = (pkg_data.get("namespace") or "").lower()
            lib_ns_counts[ns] = lib_ns_counts.get(ns, 0) + 1
        for ns in sorted(lib_ns_counts.keys(), key=lambda k: (k == "", k)):
            label = ns if ns else t("my_tools_no_namespace")
            child = QtWidgets.QListWidgetItem(
                "{} ({})".format(label, lib_ns_counts[ns]),
            )
            child.setData(Qt.UserRole, self._LIBRARY_NS_PREFIX + ns)
            self._catalogue_list.addItem(child)

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

        for lst in (self._catalogue_list, self._mytools_list):
            lst.blockSignals(False)

        # Restore or default selection
        if not self._restore_sidebar_selection(prev):
            # Default: first catalogue; fall back to My Tools "All"
            if self._catalogue_list.count() > 0:
                self._catalogue_list.setCurrentRow(0)
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
            for i in range(self._catalogue_list.count()):
                if self._catalogue_list.item(i).data(Qt.UserRole) == key:
                    self._catalogue_list.setCurrentRow(i)
                    return True
        return False

    def _on_catalogue_row_changed(self, row):
        if row < 0:
            return
        item = self._catalogue_list.item(row)
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
        self._catalogue_list.blockSignals(True)
        self._catalogue_list.clearSelection()
        self._catalogue_list.setCurrentRow(-1)
        self._catalogue_list.blockSignals(False)
        self._apply_sidebar_selection(item.data(Qt.UserRole))

    def _apply_sidebar_selection(self, key):
        """Common path for both sidebar lists."""
        self._sidebar_selection = key
        # Tells an in-flight refresh() that the cards are already being
        # rebuilt off the selection change, so it can skip its own pass.
        self._cards_rebuilt_by_sidebar = True
        is_my_tools = self._is_mytools_selection(self._sidebar_selection)
        # Show tabs for registries, register button for My Tools
        self._tab_all.setVisible(not is_my_tools)
        self._tab_installed.setVisible(not is_my_tools)
        self._register_btn.setVisible(is_my_tools)

        if not is_my_tools:
            # Default to "installed", fall back to "all" if none installed.
            # Library selection is now namespace-scoped (or "all"), so we
            # filter packages by namespace before checking which have an
            # install on disk.
            packages = self._catalogue_client.get_packages() if self._catalogue_client else {}
            installed = self._install_manager.get_installed_packages() if self._install_manager else {}
            ns_filter = self._library_ns_filter(self._sidebar_selection)
            has_installed = any(
                pkg_id in installed
                for pkg_id, pkg_data in packages.items()
                if ns_filter is None
                or (pkg_data.get("namespace") or "").lower() == ns_filter
            )
            self._current_tab = "installed" if has_installed else "all"
            self._tab_installed.setChecked(self._current_tab == "installed")
            self._tab_all.setChecked(self._current_tab == "all")

        self._rebuild_cards()

    # ---- internal ----

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
                self._catalogue_client.get_packages()
                if self._catalogue_client else {}
            )
            visible_items = self._collect_catalogue_items(packages, installed, selection)

        # pkg_id -> [writable local catalogue names], for "Published-to" badges.
        # Built once per rebuild instead of per-card.
        published_map = self._build_published_map()

        # Grouped rendering: My Tools root + Library root both render as
        # namespace trees. Per-namespace children (My Tools or Library)
        # render as a flat list — the namespace is already in the sidebar
        # label so a tree header would be redundant.
        is_mytools_root = (selection == self._MYTOOLS_KEY)
        is_library_root = (selection == self._LIBRARY_KEY)
        is_grouped_view = is_mytools_root or is_library_root
        icon_fetch_tasks = []
        ns_groups = {}  # ns_key -> (header_btn, [card widgets])

        if is_grouped_view:
            # Collapse state is tracked per-view so My Tools and Library
            # can hide the same namespace independently (applied to the
            # header after the loop completes).
            for ns, group_items in group_by_namespace(visible_items):
                header = self._create_group_header(
                    ns, is_mytools=is_mytools_root,
                )
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

        # Publish which groups (if any) the freshly built layout has, so
        # _apply_card_visibility can resolve collapse state and the
        # search query together. A flat view registers no groups.
        if is_mytools_root:
            self._mytools_groups = ns_groups
            self._active_ns_groups = ns_groups
            self._active_collapsed = self._mytools_collapsed
        elif is_library_root:
            self._library_groups = ns_groups
            self._active_ns_groups = ns_groups
            self._active_collapsed = self._library_collapsed
        else:
            self._active_ns_groups = {}
            self._active_collapsed = set()

        # Rebuilt cards start visible; this is what applies the folds and
        # the search box's current contents to them. Without it a rebuild
        # (install, publish, tab switch) silently discarded both.
        self._apply_card_visibility()

        self._start_icon_fetcher(icon_fetch_tasks)

    # ---- _rebuild_cards helpers ------------------------------------------

    # A card rebuild happens on every refresh and every sidebar click, so
    # it must not be able to hold the UI thread for longer than a pause.
    # Teardown gets a longer budget: there we would rather wait than
    # leave threads behind on the way out.
    _ICON_FETCHER_JOIN_MS = 3000
    _ICON_FETCHER_TEARDOWN_JOIN_MS = 15000

    def _stop_icon_fetcher(self, timeout_ms=None):
        """Stop any in-flight icon fetcher from a previous rebuild.

        The fetcher only checks for interruption between icons, so when
        it is parked inside a socket read this has to wait out the
        remainder of that request. Rather than block indefinitely, a
        fetcher that overruns is detached from this window and left to
        finish on its own.

        Detaching matters: the fetcher is parented to the window, and Qt
        aborts the process if a widget is destroyed while a child thread
        is still running. Cutting the parent link (and the signal back
        into the card map, which is about to be rebuilt) makes the
        straggler harmless.
        """
        fetcher = self._icon_fetcher
        self._icon_fetcher = None
        if fetcher is None or not fetcher.isRunning():
            return
        fetcher.requestInterruption()
        if fetcher.wait(timeout_ms or self._ICON_FETCHER_JOIN_MS):
            return
        try:
            fetcher.icon_ready.disconnect()
        except (RuntimeError, TypeError):
            pass
        fetcher.setParent(None)
        self._detached_fetchers = [
            f for f in self._detached_fetchers if f.isRunning()
        ]
        self._detached_fetchers.append(fetcher)

    def _shutdown_workers(self):
        """Stop background QThreads before the window goes away.

        Qt aborts the whole process ("QThread: Destroyed while thread is
        still running") if a running thread's C++ object is deleted, and
        both workers are parented to this window — so this must run on
        every teardown path (close button, workspaceControl close,
        dev-reload) before the widget is destroyed.
        """
        self._stop_icon_fetcher(self._ICON_FETCHER_TEARDOWN_JOIN_MS)
        worker = self._update_check_worker
        if worker is not None and worker.isRunning():
            # No interruption hook: the probe is a single urlopen with a
            # 10s timeout, so bound the wait rather than hanging Maya.
            worker.wait(15000)
        self._update_check_worker = None

    def closeEvent(self, event):
        self._shutdown_workers()
        super().closeEvent(event)

    def dockCloseEventTriggered(self):
        # MayaQWidgetDockableMixin calls this when the hosting
        # workspaceControl is closed — closeEvent alone doesn't fire then.
        self._shutdown_workers()
        parent_hook = getattr(super(), "dockCloseEventTriggered", None)
        if parent_hook is not None:
            parent_hook()

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
        self._icon_fetcher = IconFetcher(tasks, self._config, parent=self)
        self._icon_fetcher.icon_ready.connect(self._on_icon_ready)
        self._icon_fetcher.start()

    def _collect_mytools_items(self, installed, selection):
        """Return ``[(pkg_id, view_data)]`` for the My Tools view, sorted by ns."""
        ns_filter = self._mytools_ns_filter(selection)
        catalogue_packages = (
            self._catalogue_client.get_packages() if self._catalogue_client else {}
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
            # catalogue SoT for display_name on catalogue-side entries; My Tools
            # rows already carry their own display_name.
            item["display_name"] = resolve_display_name(
                pkg_id, pkg_data, catalogue_packages.get(pkg_id),
            )
            items.append((pkg_id, item))
        items.sort(key=lambda x: (
            (x[1].get("namespace") or "~").lower(),
            x[1].get("display_name", ""),
        ))
        return items

    def _collect_catalogue_items(self, packages, installed, selection):
        """Return ``[(pkg_id, view_data)]`` for the selected Library view.

        Library selections in v5.0 are namespace-scoped (or ``All``), so
        the filter is a simple ``pkg.namespace == selection_namespace``.
        Dedup across catalogues already happened in CatalogueClient
        (first-catalogue-wins), so we don't re-filter by catalogue here.
        """
        ns_filter = self._library_ns_filter(selection)
        items = []
        for pkg_id, pkg_data in packages.items():
            if ns_filter is not None:
                pkg_ns = (pkg_data.get("namespace") or "").lower()
                if pkg_ns != ns_filter:
                    continue
            item = dict(pkg_data)
            # A demoted (uninstalled-from-catalogue) entry stays in
            # installed.json as source="local" so it remains in My Tools,
            # but the catalogue view should show it as not-installed so
            # the user can re-install if they want.
            inst_entry = installed.get(pkg_id, {})
            is_installed = (
                pkg_id in installed
                and not is_pure_local(inst_entry)
            )
            if is_installed:
                inst = installed[pkg_id]
                item["_installed_ver"] = inst.get("version")
                # Verified badge: read sha256 from the catalogue's
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
        # Sort by (namespace, display_name) so Library "All" groups
        # visually by namespace when it gets rendered tree-style.
        # Per-namespace views still land on a stable display_name order.
        items.sort(key=lambda x: (
            (x[1].get("namespace") or "~").lower(),
            x[1].get("display_name", ""),
        ))
        return items

    def _create_group_header(self, ns, is_mytools):
        """Build the collapsible namespace header used by both grouped views.

        ``is_mytools=True`` wires clicks to the My Tools collapse set;
        ``False`` wires to the Library collapse set. The two views have
        independent collapse state so hiding a namespace in one doesn't
        affect the other.
        """
        label_text = ns if ns else t("my_tools_no_namespace")
        collapsed_set = (
            self._mytools_collapsed if is_mytools else self._library_collapsed
        )
        arrow = arrow_glyph(ns not in collapsed_set)
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
        if is_mytools:
            header.clicked.connect(
                lambda _checked=False, k=ns: self._toggle_mytools_group(k)
            )
        else:
            header.clicked.connect(
                lambda _checked=False, k=ns: self._toggle_library_group(k)
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
        icon_path = resolve_icon_path(pkg_data, self._config)
        if not icon_path:
            from carton.ui._icon_fetch import make_icon_filename
            icon_filename = make_icon_filename(pkg_data)
            base_dir = pkg_data.get("_catalogue_base_dir", "")
            is_remote = pkg_data.get("_catalogue_remote", False)
            if icon_filename and is_remote and base_dir:
                icon_fetch_tasks.append((pkg_id, base_dir, icon_filename))

        # In a catalogue view we render the same plain consumer card
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
            published_catalogues=card_published,
        )
        card.launch_requested.connect(self._on_launch)
        card.install_requested.connect(self._on_install)
        card.publish_requested.connect(self._on_publish)
        card.update_requested.connect(self._on_update)
        card.unpublish_requested.connect(self._on_card_unpublish)
        card.setCursor(Qt.PointingHandCursor)
        self._card_map[pkg_id] = card

        # Edit only opens from My Tools view. In a catalogue view the
        # user is acting as a consumer — even for packages they
        # published — so show the detail panel (with rollback /
        # version history) instead.
        if in_my_tools_view:
            card.mousePressEvent = lambda e, pid=pkg_id: self._show_edit(pid)
        else:
            card.mousePressEvent = lambda e, pid=pkg_id: self._show_detail(pid)
        return card

    def _toggle_mytools_group(self, ns_key):
        self._toggle_group(
            self._mytools_groups, self._mytools_collapsed, ns_key,
        )

    def _toggle_library_group(self, ns_key):
        self._toggle_group(
            self._library_groups, self._library_collapsed, ns_key,
        )

    def _toggle_group(self, groups, collapsed_set, ns_key):
        """Flip collapse state for a grouped view's namespace header.

        Shared between My Tools and Library since the UI affordance is
        identical — only the backing ``groups`` / ``collapsed`` sets
        differ. Only the state is flipped here; rendering it is
        _apply_card_visibility's job, so a fold made while a search is
        active doesn't drag non-matching cards back onto the screen.
        """
        if ns_key not in groups:
            return
        toggle_collapsed(collapsed_set, ns_key)
        self._apply_card_visibility()

    def _on_icon_ready(self, pkg_id, icon_path):
        """Slot called from background thread when an icon is downloaded."""
        card = self._card_map.get(pkg_id)
        if card:
            card.set_icon(icon_path)

    def _show_detail(self, pkg_id):
        packages = self._catalogue_client.get_packages() if self._catalogue_client else {}
        pkg_data = packages.get(pkg_id, {})
        installed = self._install_manager.get_installed_packages() if self._install_manager else {}
        installed_ver = installed.get(pkg_id, {}).get("version")

        # Resolve icon path for the detail panel
        icon_path = resolve_icon_path(pkg_data, self._config)

        self._detail.show_package(pkg_id, pkg_data, installed_version=installed_ver,
                                  icon_path=icon_path)
        self._stack.setCurrentIndex(1)

    def _show_edit(self, pkg_id):
        self._edit_ctl.show_edit(pkg_id)

    def _filter_cards(self, _text=None):
        # The search box's textChanged passes the text; everything else
        # calls this bare. Either way the current query is read from the
        # widget, so there is only one place it can come from.
        self._apply_card_visibility()

    def _iter_cards(self):
        for i in range(self._card_layout.count()):
            widget = self._card_layout.itemAt(i).widget()
            if isinstance(widget, PackageCard):
                yield widget

    def _apply_card_visibility(self):
        """Decide what is on screen from the query and the collapse state.

        Search and namespace collapsing both used to set card visibility
        independently, and whichever ran last won: typing in the search
        box revealed cards inside a collapsed namespace, and clearing it
        left every namespace expanded no matter what the user had folded
        away. Headers were never hidden either, so filtering left a run
        of namespace titles with nothing under them.

        Resolving both inputs in one pass is what keeps them consistent.
        A search deliberately overrides collapsing — a hit the user
        cannot see because it happens to sit in a folded namespace reads
        as "no results" — but it does so without touching the stored
        collapse state, so folding is restored when the box is cleared.
        """
        query = self._search.text() if hasattr(self, "_search") else ""
        query = (query or "").strip()
        groups = self._active_ns_groups

        if not groups:
            # Flat view: no headers, nothing to fold.
            for card in self._iter_cards():
                card.setVisible(card.matches(query))
            return

        collapsed = self._active_collapsed
        for ns, (header, cards) in groups.items():
            if query:
                any_match = False
                for card in cards:
                    hit = card.matches(query)
                    card.setVisible(hit)
                    any_match = any_match or hit
                header.setVisible(any_match)
                self._set_header_arrow(header, expanded=True)
            else:
                folded = ns in collapsed
                for card in cards:
                    card.setVisible(not folded)
                header.setVisible(True)
                self._set_header_arrow(header, expanded=not folded)

    @staticmethod
    def _set_header_arrow(header, expanded):
        """Rewrite a group header's leading chevron in place.

        Header text is ``"{arrow}  {label}"``, so the glyph is the first
        character and the label is everything from index 1 on.
        """
        text = header.text()
        if len(text) >= 3:
            header.setText(arrow_glyph(expanded) + text[1:])

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
                home_origin=result.get("home_origin"),
                include_compiled=result.get("include_compiled", False),
            )
            self._rebuild_sidebar()
            self._rebuild_cards()
        except Exception as e:
            show_error(self, e, operation="register")

    def _on_publish(self, pkg_id):
        self._publish_ctl.start_publish(pkg_id)

    def _build_published_map(self):
        return self._publish_ctl.build_published_map()

    def _on_card_unpublish(self, pkg_id, catalogue_name):
        self._publish_ctl.on_card_unpublish(pkg_id, catalogue_name)

    def _on_unpublish(self, pkg_id, catalogue_entry):
        self._publish_ctl.unpublish(pkg_id, catalogue_entry)

    def _show_history_for(self, pkg_id):
        """Open the version history dialog for a published package.

        Used from the Edit dialog flow, where the click target is the
        installed-side data (no `versions` map). We pull the catalogue
        snapshot via the catalogue client and reuse the same dialog as
        the detail panel.
        """
        if not self._catalogue_client:
            return
        packages = self._catalogue_client.get_packages()
        pkg_data = packages.get(pkg_id)
        if not pkg_data:
            QtWidgets.QMessageBox.information(
                self, "Carton", t("history_no_catalogue_data"),
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
        if self._catalogue_client:
            packages = self._catalogue_client.get_packages()
            pkg_data = packages.get(pkg_id)
            if pkg_data:
                installed = self._install_manager.get_installed_packages()
                self._detail.show_package(
                    pkg_id, pkg_data,
                    installed_version=installed.get(pkg_id, {}).get("version"),
                    icon_path=resolve_icon_path(pkg_data, self._config),
                )

    def _on_update(self, pkg_id):
        packages = self._catalogue_client.get_packages() if self._catalogue_client else {}
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
        self._self_update_ctl.check(force=force)

    def _on_self_update_check_done(self, result, error):
        self._self_update_ctl.on_check_done(result, error)

    def _on_self_update(self):
        self._self_update_ctl.apply()

    def _on_install(self, pkg_id, version=None, pinned=False):
        self._install_ctl.install(pkg_id, version=version, pinned=pinned)

    def _set_install_button_state(self, pkg_id, busy=True):
        self._install_ctl.set_install_button_state(pkg_id, busy=busy)

    def _on_uninstall(self, pkg_id):
        self._install_ctl.uninstall(pkg_id)

    def _on_launch(self, pkg_id):
        self._install_ctl.launch(pkg_id)

    def _show_launch_error(self, exc):
        self._install_ctl.show_launch_error(exc)

def create_window(parent=None):
    # In Maya, leave parent=None: MayaQWidgetDockableMixin parents us to a
    # workspaceControl when show(dockable=True) is called. Forcing the Maya
    # main window as parent here would compete with that and produce orphaned
    # floating widgets when the workspaceControl is closed.
    return CartonWindow(parent)
