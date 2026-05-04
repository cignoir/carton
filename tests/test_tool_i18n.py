"""Tests for ``carton.tool_i18n`` — the tool-side i18n helper that
follows Carton's UI language.

Two surfaces:

* :class:`Translator` + module-level helpers — translation lookup with
  graceful fallback (active language → ``en`` → raw key) and JSON
  loading from ``i18n/<lang>.json``.
* The C+D contract: a tool's ``set_language(code)`` is callable from
  Carton's launch path and the env var fallback works for tools that
  skip the hook.
"""

import json
import os

import pytest

import carton.tool_i18n as ti18n


@pytest.fixture(autouse=True)
def _isolate_state(monkeypatch):
    """Each test runs with a fresh language state and a clean env var
    so cross-test ordering can't mask a real bug."""
    # Reset module-level active language
    ti18n._active_lang = None
    monkeypatch.delenv(ti18n.ENV_VAR, raising=False)
    yield
    ti18n._active_lang = None


# ---------------------------------------------------------------------------
# Language state
# ---------------------------------------------------------------------------


def test_set_language_normalizes_region_suffix():
    ti18n.set_language("en-US")
    assert ti18n.get_language() == "en"
    ti18n.set_language("ja_JP")
    assert ti18n.get_language() == "ja"


def test_set_language_ignores_empty_input():
    """Empty or whitespace shouldn't clobber a previously-set language —
    otherwise a missing CARTON_LANGUAGE could erase the user's choice."""
    ti18n.set_language("ja")
    ti18n.set_language("")
    ti18n.set_language(None)
    ti18n.set_language("   ")
    assert ti18n.get_language() == "ja"


def test_detect_language_from_env_var(monkeypatch):
    monkeypatch.setenv(ti18n.ENV_VAR, "ja-JP")
    assert ti18n.detect_language() == "ja"


def test_detect_language_falls_back_to_en(monkeypatch):
    """With no env var, no Maya, and a stripped locale, we shouldn't
    raise — just settle on English."""
    monkeypatch.setenv(ti18n.ENV_VAR, "")
    for k in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(k, raising=False)
    import locale as _locale
    monkeypatch.setattr(_locale, "getlocale", lambda: (None, None))
    assert ti18n.detect_language() == "en"


def test_get_language_lazy_detects_on_first_call(monkeypatch):
    """The active language stays unresolved until something asks for it
    so Carton can set CARTON_LANGUAGE just before launch and have the
    env var picked up at the latest possible moment."""
    monkeypatch.setenv(ti18n.ENV_VAR, "fr")
    assert ti18n._active_lang is None
    assert ti18n.get_language() == "fr"


# ---------------------------------------------------------------------------
# Translator
# ---------------------------------------------------------------------------


def _write_locales(pkg_dir, mapping):
    """Helper: drop ``i18n/<lang>.json`` files into ``pkg_dir``."""
    i18n_dir = pkg_dir / "i18n"
    i18n_dir.mkdir()
    for lang, strings in mapping.items():
        (i18n_dir / "{}.json".format(lang)).write_text(
            json.dumps(strings, ensure_ascii=False), encoding="utf-8",
        )


def test_translator_loads_json_files(tmp_path):
    _write_locales(tmp_path, {
        "en": {"greet": "Hello"},
        "ja": {"greet": "こんにちは"},
    })
    tr = ti18n.Translator(tmp_path)
    ti18n.set_language("ja")
    assert tr.t("greet") == "こんにちは"
    ti18n.set_language("en")
    assert tr.t("greet") == "Hello"


def test_translator_falls_back_to_english(tmp_path):
    _write_locales(tmp_path, {"en": {"greet": "Hello"}})
    tr = ti18n.Translator(tmp_path)
    ti18n.set_language("ja")  # ja file missing
    assert tr.t("greet") == "Hello"


def test_translator_falls_back_to_raw_key(tmp_path):
    _write_locales(tmp_path, {"en": {"greet": "Hello"}})
    tr = ti18n.Translator(tmp_path)
    ti18n.set_language("ja")
    # Key not present in any file → raw key surfaces (debuggable)
    assert tr.t("missing.key") == "missing.key"


def test_translator_format_args_apply(tmp_path):
    _write_locales(tmp_path, {
        "en": {"hello": "Hello {name}"},
        "ja": {"hello": "{name}さん、こんにちは"},
    })
    tr = ti18n.Translator(tmp_path)
    ti18n.set_language("ja")
    assert tr.t("hello", name="ばぶ") == "ばぶさん、こんにちは"


def test_translator_format_failure_returns_unformatted(tmp_path):
    """A typo in a translation that breaks str.format must not crash —
    surface the unformatted text instead."""
    _write_locales(tmp_path, {"en": {"bad": "Hello {nope"}})
    tr = ti18n.Translator(tmp_path)
    assert tr.t("bad", name="x") == "Hello {nope"


def test_translator_handles_missing_i18n_dir(tmp_path):
    """No ``i18n/`` folder shouldn't raise — the tool just gets raw keys."""
    tr = ti18n.Translator(tmp_path)
    assert tr.t("anything") == "anything"


def test_translator_handles_malformed_json(tmp_path):
    i18n_dir = tmp_path / "i18n"
    i18n_dir.mkdir()
    (i18n_dir / "en.json").write_text("not json {", encoding="utf-8")
    (i18n_dir / "ja.json").write_text(
        json.dumps({"greet": "やあ"}), encoding="utf-8",
    )
    tr = ti18n.Translator(tmp_path)
    # English file broken → ja still loads
    ti18n.set_language("ja")
    assert tr.t("greet") == "やあ"


def test_translator_skips_non_string_values(tmp_path):
    """Translation files with accidental non-string values should drop
    those entries rather than crash later in t()."""
    i18n_dir = tmp_path / "i18n"
    i18n_dir.mkdir()
    (i18n_dir / "en.json").write_text(
        json.dumps({"good": "ok", "bad": ["wrong"], "also_bad": 42}),
        encoding="utf-8",
    )
    tr = ti18n.Translator(tmp_path)
    assert tr.t("good") == "ok"
    assert tr.t("bad") == "bad"  # silently dropped → raw key
    assert tr.t("also_bad") == "also_bad"


def test_translator_finds_i18n_in_parent_dir(tmp_path):
    """Some tools nest UI in a subpackage — the Translator looks one
    level up if there's no ``i18n/`` next to ``package_dir``."""
    sub = tmp_path / "ui"
    sub.mkdir()
    _write_locales(tmp_path, {"en": {"k": "v"}})
    tr = ti18n.Translator(sub)
    assert tr.t("k") == "v"


# ---------------------------------------------------------------------------
# C+D launch hook contract — exercised via ScriptManager
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_modules():
    """Snapshot sys.modules so test-injected packages don't leak."""
    import sys
    saved = set(sys.modules.keys())
    saved_path = list(sys.path)
    yield
    sys.path[:] = saved_path
    for m in list(sys.modules.keys()):
        if m not in saved:
            del sys.modules[m]


def _write_pkg(parent_dir, name, body):
    """Write a one-shot test package whose __init__.py is ``body``."""
    pkg = parent_dir / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text(body, encoding="utf-8")
    return name, str(pkg)


def _pkg_data(local_path, module_name):
    return {
        "type": "python_package",
        "source": "local",
        "local_path": local_path,
        "is_folder": True,
        "entry_point": {
            "type": "python",
            "module": module_name,
            "function": "show",
        },
    }


def test_launch_calls_set_language_when_present(tmp_path, clean_modules):
    """A tool that exposes ``set_language`` should receive the active
    language before its entry point runs."""
    from carton.core.script_manager import ScriptManager
    from carton.core.env_manager import MayaEnvManager
    from carton.core.config import Config
    from carton.ui.i18n import set_language as ui_set_language

    name, pkg_dir = _write_pkg(tmp_path, "ti18n_hook_pkg", """
_received = None
_called_before_show = False
_show_ran = False

def set_language(code):
    global _received, _called_before_show
    _received = code
    _called_before_show = not _show_ran

def show():
    global _show_ran
    _show_ran = True
""")
    # Drive Carton's UI language
    ui_set_language("ja")

    sm = ScriptManager(config=Config(), install_manager=None,
                       env_manager=MayaEnvManager())
    sm.launch(_pkg_data(pkg_dir, name))

    import sys
    mod = sys.modules[name]
    assert mod._received == "ja"
    assert mod._called_before_show is True
    assert mod._show_ran is True


def test_launch_sets_env_var_for_tools_without_hook(tmp_path, clean_modules):
    """A tool that doesn't implement set_language should still see the
    active language via CARTON_LANGUAGE — the Layer 2 fallback."""
    from carton.core.script_manager import ScriptManager
    from carton.core.env_manager import MayaEnvManager
    from carton.core.config import Config
    from carton.ui.i18n import set_language as ui_set_language
    import os as _os

    name, pkg_dir = _write_pkg(tmp_path, "ti18n_envvar_pkg", """
import os
_seen_env = None

def show():
    global _seen_env
    _seen_env = os.environ.get('CARTON_LANGUAGE')
""")
    ui_set_language("ja")
    sm = ScriptManager(config=Config(), install_manager=None,
                       env_manager=MayaEnvManager())
    sm.launch(_pkg_data(pkg_dir, name))

    import sys
    assert sys.modules[name]._seen_env == "ja"
    assert _os.environ.get("CARTON_LANGUAGE") == "ja"


def test_launch_swallows_set_language_errors(tmp_path, clean_modules):
    """A buggy ``set_language`` must not block the tool from launching —
    show() should still run."""
    from carton.core.script_manager import ScriptManager
    from carton.core.env_manager import MayaEnvManager
    from carton.core.config import Config

    name, pkg_dir = _write_pkg(tmp_path, "ti18n_buggy_pkg", """
_show_ran = False

def set_language(code):
    raise ValueError("boom")

def show():
    global _show_ran
    _show_ran = True
""")
    sm = ScriptManager(config=Config(), install_manager=None,
                       env_manager=MayaEnvManager())
    sm.launch(_pkg_data(pkg_dir, name))  # should not raise

    import sys
    assert sys.modules[name]._show_ran is True
