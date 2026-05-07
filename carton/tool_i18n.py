"""Tool-side i18n helper that follows Carton's UI language.

Two pieces fit together:

1. **Contract (Layer 1)** — a tool exposes ``set_language(code: str)`` at
   the top of its package. Carton calls it just before invoking the
   ``entry_point`` so the tool's UI inherits Carton's active language.
   Tools that don't implement it are silently skipped (backward
   compatible).

2. **Helper (Layer 2)** — this module ships with Carton and gives tool
   authors a batteries-included translator:

   .. code-block:: python

       # my_tool/__init__.py
       from carton.tool_i18n import for_caller, set_language  # re-exports

       _tr = for_caller()
       t = _tr.t

       def show():
           from .ui import MyWindow
           MyWindow().show()

   With ``i18n/en.json`` and ``i18n/ja.json`` placed next to the
   package's ``__init__.py``, the tool gets:

   * Auto-loaded translations on first ``t()`` call.
   * Active language synced to Carton when launched through Carton.
   * Sensible fallback when run standalone (env var → Maya UI locale →
     system locale → ``"en"``).
   * Re-export of ``set_language`` from this module so the launch
     contract is satisfied by a single import — no boilerplate.

The language state is **process-global**: if multiple tools share this
helper, ``set_language`` switches them all at once. That matches how
Carton wants to drive a single-language session and avoids having every
tool re-detect for itself.
"""

from __future__ import annotations

import inspect
import json
import locale as _locale
import os
import sys
from pathlib import Path
from typing import Optional


__all__ = [
    "Translator",
    "detect_language",
    "for_caller",
    "get_language",
    "set_language",
]


# Process-global active language. Lazy: stays None until first read so
# detect_language() runs at the latest possible moment, picking up any
# CARTON_LANGUAGE env var Carton sets just before launch.
_active_lang: Optional[str] = None

# The env var Carton sets before invoking a tool's entry point. Tools
# that skip the set_language hook can still pick it up via
# detect_language().
ENV_VAR = "CARTON_LANGUAGE"


# ---------------------------------------------------------------------------
# Language state
# ---------------------------------------------------------------------------


def _normalize(code: str) -> str:
    """Reduce a locale code to its stem (``en-US`` → ``en``)."""
    if not isinstance(code, str):
        return ""
    code = code.strip()
    if not code:
        return ""
    # Accept en_US / en-US / en.UTF-8 / en alike
    for sep in ("-", "_", "."):
        if sep in code:
            code = code.split(sep, 1)[0]
            break
    return code.lower()


def detect_language() -> str:
    """Pick the best language for an unspecified context.

    Resolution order:

    1. ``CARTON_LANGUAGE`` env var — set by Carton just before launch.
    2. Maya UI locale (``cmds.about(uiLanguage=True)``) — when the host
       is Maya and the user picked a localized UI.
    3. System default locale.
    4. ``"en"`` as a last resort.
    """
    env = os.environ.get(ENV_VAR, "")
    stem = _normalize(env)
    if stem:
        return stem

    try:
        import maya.cmds as cmds  # type: ignore[import-not-found]
        ui = cmds.about(uiLanguage=True)
        stem = _normalize(ui or "")
        if stem:
            return stem
    except ImportError:
        pass
    except RuntimeError:
        # Maya present but ``about`` failed — fall through to system locale.
        pass

    stem = _normalize(_system_locale())
    if stem:
        return stem

    return "en"


def _system_locale() -> str:
    """Best-effort system locale lookup that survives the
    ``locale.getdefaultlocale`` deprecation in Python 3.15.

    Reads, in order: ``locale.getlocale()`` (the active C-runtime
    setting) and the ``LC_ALL`` / ``LC_MESSAGES`` / ``LANG`` /
    ``LANGUAGE`` environment variables. Returns ``""`` if none are
    populated.
    """
    try:
        code, _ = _locale.getlocale()
        if code:
            return code
    except (ValueError, TypeError):
        pass
    for key in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(key, "")
        if v:
            return v
    return ""


def set_language(code: str) -> None:
    """Set the active language for every tool using this helper.

    Carton invokes this on the tool's top-level package automatically
    when the user clicks Launch. Tools may also call it themselves —
    e.g. to honour a stored per-tool preference on first run.

    Empty / falsy codes are ignored so an unset env var doesn't clobber
    a previously chosen language.
    """
    global _active_lang
    stem = _normalize(code or "")
    if stem:
        _active_lang = stem


def get_language() -> str:
    """Return the active language code, detecting one if unset."""
    global _active_lang
    if _active_lang is None:
        _active_lang = detect_language()
    return _active_lang


# ---------------------------------------------------------------------------
# Translator
# ---------------------------------------------------------------------------


class Translator:
    """Per-package string lookup backed by ``i18n/<lang>.json`` files.

    Pass the directory containing the JSON files (or its parent — the
    Translator looks for an ``i18n/`` subdir). Each JSON file is a flat
    ``{key: string}`` map; the file's stem (``"en"``, ``"ja"``, ...) is
    the language code.

    Resolution falls back through: requested language → ``"en"`` → the
    raw key (so an untranslated string at least surfaces something
    debuggable).
    """

    def __init__(self, package_dir: os.PathLike | str):
        self.package_dir = Path(package_dir).resolve()
        self.strings: dict[str, dict[str, str]] = {}
        self._load()

    # ------------------------------------------------------------------
    # JSON loading
    # ------------------------------------------------------------------

    def _i18n_dir(self) -> Optional[Path]:
        """Find an ``i18n/`` directory under ``package_dir`` or its parent.

        Tools tend to be either ``my_tool/i18n/`` (preferred — JSON
        sits next to ``__init__.py``) or ``my_tool/<sub>/i18n/`` (legacy
        — search one level up). Either layout works.
        """
        for c in (self.package_dir, self.package_dir.parent):
            candidate = c / "i18n"
            if candidate.is_dir():
                return candidate
        return None

    def _load(self) -> None:
        i18n_dir = self._i18n_dir()
        if i18n_dir is None:
            return
        for path in sorted(i18n_dir.glob("*.json")):
            stem = _normalize(path.stem)
            if not stem:
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                # A malformed file shouldn't break the whole tool —
                # surface untranslated keys instead.
                continue
            if not isinstance(data, dict):
                continue
            self.strings[stem] = {
                k: v for k, v in data.items()
                if isinstance(k, str) and isinstance(v, str)
            }

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def t(self, key: str, *args, **kwargs) -> str:
        """Translate ``key`` for the active language.

        Format args are forwarded to ``str.format``; format failures are
        swallowed so a typo in a translation can't crash the UI.
        """
        lang = get_language()
        text = self.strings.get(lang, {}).get(key)
        if text is None:
            text = self.strings.get("en", {}).get(key)
        if text is None:
            return key
        if args or kwargs:
            try:
                return text.format(*args, **kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text


# ---------------------------------------------------------------------------
# Caller convenience
# ---------------------------------------------------------------------------


def for_caller() -> Translator:
    """Return a :class:`Translator` whose ``package_dir`` is the directory
    of the module that called this function.

    Lets a tool's ``__init__.py`` write::

        from carton.tool_i18n import for_caller
        _tr = for_caller()
        t = _tr.t

    without restating its own filesystem location. Falls back to the
    current working directory if the caller frame doesn't carry a
    ``__file__`` (e.g. interactive REPL).
    """
    frame = inspect.stack()[1]
    mod_name = frame.frame.f_globals.get("__name__", "")
    mod = sys.modules.get(mod_name)
    if mod is not None:
        path = getattr(mod, "__file__", None)
        if path:
            return Translator(Path(path).parent)
    return Translator(Path.cwd())
