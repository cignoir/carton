"""Type-specific handlers."""

from carton.core.handlers.python_handler import PythonPackageHandler
from carton.core.handlers.mel_handler import MelScriptHandler
from carton.core.handlers.plugin_handler import PluginHandler
from carton.core.handlers.local_handler import LocalHandler

_HANDLERS = {
    "python_package": PythonPackageHandler,
    "mel_script": MelScriptHandler,
    "plugin": PluginHandler,
    "local": LocalHandler,
}


def get_handler(package_type):
    """Return a Handler instance corresponding to the given type."""
    handler_cls = _HANDLERS.get(package_type, PythonPackageHandler)
    return handler_cls()
