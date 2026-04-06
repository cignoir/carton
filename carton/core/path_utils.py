"""Portable path helpers for ``local_path`` values persisted to installed.json.

Locally-registered tools (My Tools) store the user-supplied path verbatim,
which means a tool registered as ``C:\\Users\\alice\\tools\\rigger.py`` breaks
the moment the user's home directory is renamed, they move to a different
machine, or they sync ``installed.json`` across machines.

This module provides two symmetric helpers:

    store_local_path(absolute)  ->  portable form written to installed.json
    resolve_local_path(stored)  ->  absolute path to actually use

The portable form collapses the user's home directory to ``~`` and leaves
any existing environment-variable references (``$VAR`` / ``%VAR%``)
untouched. On read, both are expanded.

This is intentionally minimalist — it covers the two common sources of
breakage (home-dir rename, cross-machine sync with an env anchor) without
introducing a full project-root abstraction.
"""

import os


def store_local_path(path):
    """Convert an absolute path to its portable form for persistence.

    * Collapses the user's home directory to ``~``
    * Leaves ``$VAR`` / ``%VAR%`` references alone (callers can pre-insert
      them manually if they want an env-anchored path)
    * Leaves paths that don't live under ``~`` as-is

    Args:
        path: Absolute path (or already-portable path) to store.

    Returns:
        Portable path string suitable for installed.json.
    """
    if not path:
        return path
    # If it already contains env-var tokens, trust the caller — don't
    # re-expand and re-collapse, which could mangle the intent.
    if "$" in path or "%" in path:
        return path

    home = os.path.expanduser("~")
    norm_path = os.path.normpath(path)
    norm_home = os.path.normpath(home)
    # Only collapse when the path is actually inside the home directory.
    try:
        rel = os.path.relpath(norm_path, norm_home)
    except ValueError:
        # Different drives on Windows — no common ancestor.
        return norm_path
    if rel.startswith("..") or os.path.isabs(rel):
        return norm_path
    # Use forward slashes after "~" for cross-platform consistency; this
    # mirrors how most config files are written. resolve_local_path handles
    # either separator via os.path.expanduser + normpath.
    return "~/" + rel.replace(os.sep, "/")


def resolve_local_path(stored):
    """Expand a stored portable path to an absolute filesystem path.

    Applies ``expanduser`` and ``expandvars`` so both ``~`` and environment
    variables resolve against the current session.

    Args:
        stored: Value read from installed.json's ``local_path`` field.

    Returns:
        Absolute path, normalized for the current platform. If ``stored``
        is falsy, returns it verbatim.
    """
    if not stored:
        return stored
    expanded = os.path.expandvars(os.path.expanduser(stored))
    return os.path.normpath(expanded)
