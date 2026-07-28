"""Carton — Maya Package Manager.

Usage:
    import carton
    carton.show()
"""

__version__ = "0.5.12"

_window = None
_initialized = False
_config = None
_env_mgr = None
_install_mgr = None
_catalogue_client = None
_downloader = None
_self_updater = None
_script_mgr = None
_publisher = None


def startup():
    """Initialization called from the bootstrap at Maya startup."""
    global _initialized, _config, _env_mgr, _install_mgr
    global _catalogue_client, _downloader, _self_updater, _script_mgr, _publisher
    if _initialized:
        return
    _initialized = True

    from carton.core.config import Config
    from carton.core.env_manager import MayaEnvManager
    from carton.core.installer import InstallManager
    # v5.0: CatalogueClient understands both v4.0 registries
    # (auto-migrated in memory) and v5.0 catalogues with the Origin
    # abstraction. The legacy RegistryClient has been removed; its API
    # was a subset of this one.
    from carton.core.catalogue.client import CatalogueClient
    from carton.core.downloader import Downloader
    from carton.core.self_updater import SelfUpdater
    from carton.core.script_manager import ScriptManager
    from carton.core.publisher import Publisher

    _config = Config.load()
    # Respect a user-configured HTTP proxy before any network call fires.
    _config.apply_proxy_to_env()

    # Initialize i18n
    from carton.ui.i18n import set_language, detect_language
    lang = _config.language
    if lang == "auto":
        lang = detect_language()
    set_language(lang)

    _env_mgr = MayaEnvManager()
    _install_mgr = InstallManager(_config, _env_mgr)
    # CatalogueClient understands v5.0 catalogue.json directly and
    # auto-migrates v4.0 registry.json on first read.
    _catalogue_client = CatalogueClient(_config)
    _downloader = Downloader(_config)
    _self_updater = SelfUpdater(_config, _downloader)
    _script_mgr = ScriptManager(_config, _install_mgr, _env_mgr)
    _publisher = Publisher(_config)

    # Activate installed packages
    _install_mgr.activate_all()
    from carton.core.install_state import is_my_tools
    for pid, pdata in _install_mgr.get_installed_packages().items():
        if is_my_tools(pdata):
            _script_mgr.activate(pid)
    _env_mgr.flush()

    # Staging is a cache of zips in transit; only the success paths
    # delete them, so failed installs and abandoned publishes pile up
    # there forever. Sweep once per session, best-effort.
    from carton.core.staging import sweep_all as _sweep_staging
    from carton.core.log import get_logger
    try:
        _sweep_staging(_config)
    except Exception as e:
        get_logger().warning("staging sweep skipped: %s", e)

    # Register menu (deferred until Maya UI is initialized)
    try:
        from carton.ui.shelf import setup as _setup_ui
        _setup_ui()
    except Exception as e:
        # Outside Maya (headless import, tests) there is no shelf to
        # build. Inside Maya this is how the Carton menu appears, so a
        # silent swallow here is a missing menu with no explanation.
        get_logger().warning("could not register the Carton menu: %s", e)

    get_logger().info("v%s ready", __version__)


def show():
    """Launch the Carton package manager window.

    In Maya the window is shown as a dockable workspaceControl — users can
    drag-tab it next to the Outliner / Channel Box like any native panel.
    Re-invoking ``carton.show()`` re-uses the existing widget so dock state
    isn't lost between opens.
    """
    global _window

    if not _initialized:
        startup()

    from carton.ui.main_window import create_window
    from carton.ui.compat import isValid

    if _window is None or not isValid(_window):
        _window = create_window()
        _window.set_services(
            catalogue_client=_catalogue_client,
            install_manager=_install_mgr,
            downloader=_downloader,
            self_updater=_self_updater,
            config=_config,
            script_manager=_script_mgr,
            publisher=_publisher,
        )
        _window.deferred_init()

    # MayaQWidgetDockableMixin.show accepts ``dockable=True`` to wrap the
    # widget in a workspaceControl. A plain QWidget.show takes no kwargs,
    # so fall back to the bare call when running outside Maya.
    try:
        _window.show(dockable=True)
    except TypeError:
        _window.show()
    _window.raise_()
    _window.activateWindow()
    return _window


def open_settings():
    """Open the settings dialog directly."""
    if not _initialized:
        startup()
    from carton.ui.settings_dialog import SettingsDialog
    dialog = SettingsDialog(_config, self_updater=_self_updater)
    dialog.exec_()
