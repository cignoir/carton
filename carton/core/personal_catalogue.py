"""Personal catalogue — URL 直指定 single-package の受け皿.

Settings > Add > "Add package by URL" や GitHub add dialog で単品 repo を
受け取ったときに、CatalogueEntry に登録する代わりにここへ積む。plan v5.0
では「全 package は何らかの catalogue 配下」という統一を保つため、購読
catalogue 群と別に "personal catalogue" をローカルに持たせる。

仕様:

* 保存先: ``~/.carton/personal_catalogue.json``(``Config.install_dir`` と
  独立 — user home 直下の固定パス)。install_dir を移動しても personal
  catalogue は追従しない、machine-local な ad-hoc 購読という割り切り。
* スキーマ: v5.0 catalogue.json と同形
  (``schema_version: "5.0"``, ``catalogue_id``(初回生成して固定),
  ``display_name: "Personal"``, ``packages: {...}``).
* 重複 pkg_id は既存優先(silent replace せず False を返す)。
* pkg_id の decode 責任は caller 側: 本モジュールは既に decode 済みの
  ``<namespace>/<name>`` を受け取るだけで、package.json から decode する
  のは ``_add_github`` 側の責任。
"""

import json
import os

from carton.core.uuid_id import new_uuid


PERSONAL_CATALOGUE_FILENAME = "personal_catalogue.json"
PERSONAL_DISPLAY_NAME = "Personal"
SCHEMA_VERSION = "5.0"


def derive_pkg_id(pkg_data):
    """Return ``"namespace/name"`` from a parsed ``package.json`` dict, or ``""``.

    Used by the Settings > Add GitHub flow to decide whether a probed
    ``package.json`` describes a valid single-package repo. Lower-cases
    both components to match the v5.0 catalogue schema's allowed key
    pattern; an empty return means the dict is not suitable for
    personal-catalogue registration (caller falls through to the
    catalogue.json probe path).
    """
    if not isinstance(pkg_data, dict):
        return ""
    ns = (pkg_data.get("namespace") or "").strip().lower()
    name = (pkg_data.get("name") or "").strip().lower()
    if not ns or not name:
        return ""
    return "{}/{}".format(ns, name)


def default_path():
    """Return ``~/.carton/personal_catalogue.json``.

    Intentionally bypasses :mod:`carton.core.config` — personal catalogue
    lives under the user home, not the configurable ``install_dir``.
    """
    return os.path.join(os.path.expanduser("~"), ".carton", PERSONAL_CATALOGUE_FILENAME)


class PersonalCatalogue(object):
    """Local catalogue for ad-hoc single-package URL subscriptions.

    Instances are constructed via :meth:`load` — direct ``__init__`` use
    is also supported for tests that want a blank in-memory catalogue.
    """

    def __init__(self, catalogue_id="", display_name=PERSONAL_DISPLAY_NAME, packages=None):
        self._catalogue_id = (catalogue_id or new_uuid()).strip().lower()
        self._display_name = display_name or PERSONAL_DISPLAY_NAME
        self._packages = dict(packages or {})

    # ---- identity ---------------------------------------------------------

    @property
    def catalogue_id(self):
        return self._catalogue_id

    @property
    def display_name(self):
        return self._display_name

    @property
    def packages(self):
        """Return a live dict ``{pkg_id: pkg_data}``.

        The dict is the internal storage — callers that mutate it must
        follow up with :meth:`save`. Most callers should use the
        ``add_*`` / ``remove`` helpers instead.
        """
        return self._packages

    # ---- membership -------------------------------------------------------

    def contains(self, pkg_id):
        return pkg_id in self._packages

    def add_github_package(self, pkg_id, repo):
        """Register a github-origin entry for ``pkg_id`` → ``repo``.

        Returns True when the entry was newly added, False when ``pkg_id``
        already exists (no overwrite). Callers wanting to replace an
        entry must :meth:`remove` first.
        """
        if not pkg_id or not repo:
            return False
        if pkg_id in self._packages:
            return False
        self._packages[pkg_id] = {
            "origin": {"type": "github", "repo": repo},
        }
        return True

    def add_url_package(self, pkg_id, url):
        """Register a url-origin entry for ``pkg_id`` → ``url``."""
        if not pkg_id or not url:
            return False
        if pkg_id in self._packages:
            return False
        self._packages[pkg_id] = {
            "origin": {"type": "url", "url": url},
        }
        return True

    def remove(self, pkg_id):
        """Delete ``pkg_id``. Returns True when it existed."""
        if pkg_id in self._packages:
            del self._packages[pkg_id]
            return True
        return False

    # ---- serialisation ----------------------------------------------------

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "catalogue_id": self._catalogue_id,
            "display_name": self._display_name,
            "packages": dict(self._packages),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        return cls(
            catalogue_id=data.get("catalogue_id", ""),
            display_name=data.get("display_name", PERSONAL_DISPLAY_NAME),
            packages=data.get("packages") or {},
        )

    @classmethod
    def load(cls, path=None):
        """Load from ``path`` (default: :func:`default_path`).

        A missing file returns a fresh empty instance with a newly
        generated ``catalogue_id``. Parse failures are swallowed — we
        prefer an empty catalogue over crashing the UI on first launch,
        and a subsequent :meth:`save` will rewrite the broken file.
        """
        path = path or default_path()
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(data)

    def save(self, path=None):
        """Write to ``path`` (default: :func:`default_path`).

        Creates parent directories as needed. Overwrites atomically via
        a temp file so a partial write never corrupts the existing one.
        """
        path = path or default_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
