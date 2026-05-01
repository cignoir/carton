"""Icon resolution + background fetcher for the package card grid.

The card list pulls icons from three places:

1. An absolute path embedded in the package's ``icon`` field (My Tools
   / personal-shelf entries that point at an on-disk image).
2. A local catalogue: ``<base_dir>/icons/<filename>`` next to the
   catalogue.json.
3. A remote catalogue: cached under ``Config.icon_cache_dir`` after a
   first network fetch.

This module owns the synchronous resolution (cases 1 and 2) and the
background QThread that handles case 3 in bulk so the UI stays
responsive while a fresh remote catalogue paints its cards.
"""

import os
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from carton.ui.compat import QtCore


def make_icon_filename(pkg_data):
    """Return the bare icon filename (e.g. ``"AriMirror.png"``) for a package.

    Resolution order:
      1. If ``icon`` is a string ending in an image extension, treat it
         as the filename and return its basename verbatim — preserves
         whatever the package author chose, including PascalCase /
         non-ASCII names.
      2. If ``icon`` is the literal ``"@auto"``, fall back to
         ``<name>.png``.
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


def resolve_icon_path(pkg_data, config):
    """Resolve a local file path for ``pkg_data``'s icon, or ``None``.

    Inspects on-disk paths and the local mirror under each catalogue's
    ``icons/`` directory. For remote catalogues, only returns a path
    when the icon has already been cached — kicking off a fresh fetch
    is the :class:`IconFetcher` thread's job.
    """
    icon_value = pkg_data.get("icon", "")
    if (isinstance(icon_value, str)
            and icon_value.endswith((".png", ".jpg", ".svg"))
            and os.path.isabs(icon_value)
            and os.path.exists(icon_value)):
        return icon_value

    icon_filename = make_icon_filename(pkg_data)
    if not icon_filename:
        return None

    base_dir = pkg_data.get("_catalogue_base_dir", "")
    is_remote = pkg_data.get("_catalogue_remote", False)
    if not base_dir:
        return None
    if is_remote:
        if config:
            cached = os.path.join(config.icon_cache_dir, icon_filename)
            if os.path.exists(cached):
                return cached
    else:
        candidate = os.path.join(base_dir, "icons", icon_filename)
        if os.path.exists(candidate):
            return candidate
    return None


def fetch_remote_icon(base_url, icon_filename, config):
    """Download a remote icon synchronously and return the cached path.

    Returns ``None`` on network failure or missing config. Callers in
    the hot UI path should prefer :class:`IconFetcher` instead.
    """
    if not config or not icon_filename:
        return None
    cache_dir = config.icon_cache_dir
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
    except (URLError, OSError):
        return None


class IconFetcher(QtCore.QThread):
    """Background thread that downloads remote catalogue icons in bulk.

    Emits ``icon_ready(pkg_id, local_path)`` per successful icon. The
    main window connects this to its card-icon-update slot. Already-
    cached icons emit immediately so cards still get their picture even
    when the catalogue hasn't been fetched fresh this session.
    """

    icon_ready = QtCore.Signal(str, str)  # (pkg_id, local_path)

    def __init__(self, tasks, config, parent=None):
        """``tasks``: list of ``(pkg_id, base_url, icon_filename)``."""
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
            except (URLError, OSError):
                pass
        # Keep the cache from growing unboundedly across sessions.
        from carton.core.icon_cache import enforce_size_limit
        enforce_size_limit(cache_dir)
