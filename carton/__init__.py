"""Carton — Maya Package Manager.

Usage:
    import carton
    carton.show()
"""

__version__ = "0.1.16"

_window = None
_initialized = False
_config = None
_env_mgr = None
_install_mgr = None
_registry_client = None
_downloader = None
_self_updater = None
_script_mgr = None
_publisher = None


def startup():
    """Initialization called from the bootstrap at Maya startup."""
    global _initialized, _config, _env_mgr, _install_mgr
    global _registry_client, _downloader, _self_updater, _script_mgr, _publisher
    if _initialized:
        return
    _initialized = True

    from carton.core.config import Config
    from carton.core.env_manager import MayaEnvManager
    from carton.core.installer import InstallManager
    from carton.core.registry_client import RegistryClient
    from carton.core.downloader import Downloader
    from carton.core.self_updater import SelfUpdater
    from carton.core.script_manager import ScriptManager
    from carton.core.publisher import Publisher

    _config = Config.load()

    # Initialize i18n
    from carton.ui.i18n import set_language, detect_language
    lang = _config.language
    if lang == "auto":
        lang = detect_language()
    set_language(lang)

    _env_mgr = MayaEnvManager()
    _install_mgr = InstallManager(_config, _env_mgr)
    _registry_client = RegistryClient(_config)
    _downloader = Downloader(_config)
    _self_updater = SelfUpdater(_config, _downloader)
    _script_mgr = ScriptManager(_config, _install_mgr, _env_mgr)
    _publisher = Publisher(_config)

    # Activate installed packages
    _install_mgr.activate_all()
    for pid, pdata in _install_mgr.get_installed_packages().items():
        if pdata.get("source") in ("local_script", "published"):
            _script_mgr.activate(pid)
    _env_mgr.flush()

    # Register menu (deferred until Maya UI is initialized)
    try:
        from carton.ui.shelf import setup as _setup_ui
        _setup_ui()
    except Exception:
        pass

    print("[Carton] v{} ready".format(__version__))


def show():
    """Launch the Carton package manager window."""
    global _window

    if not _initialized:
        startup()

    from carton.ui.main_window import create_window
    _window = create_window()
    _window.set_services(
        registry_client=_registry_client,
        install_manager=_install_mgr,
        downloader=_downloader,
        self_updater=_self_updater,
        config=_config,
        script_manager=_script_mgr,
        publisher=_publisher,
    )
    _window.show()
    _window.deferred_init()
    return _window


def open_settings():
    """Open the settings dialog directly."""
    if not _initialized:
        startup()
    from carton.ui.settings_dialog import SettingsDialog
    dialog = SettingsDialog(_config)
    dialog.exec_()
