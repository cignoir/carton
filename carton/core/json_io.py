"""Crash-safe JSON read/write for the state files Carton owns.

Every file Carton persists (config.json, installed.json, catalogue.json,
the personal catalogue, profiles, source cache entries, pending_update.json)
is state the user cannot reconstruct by hand. Two rules apply to all of
them, and this module is the single place both are implemented:

**Writes are atomic.** ``json.dump`` straight onto the live path leaves a
truncated file if the process dies mid-write — and for several of these
files a truncated read is fatal at startup. Writing to a sibling temp file
and ``os.replace``-ing it into position makes the swap a single filesystem
operation: readers see either the old file or the new one, never a half.

**Reads of startup-critical files degrade instead of raising.**
:func:`read_json_quarantining` moves an unparseable file aside and hands
back a caller-supplied default, so a corrupt file costs the user the
contents of that one file rather than the ability to launch Carton at all.
The quarantined copy is kept (never deleted) so the data can be recovered
by hand or inspected in a bug report.

Callers that *want* a hard failure on malformed input — schema validation,
lint, anything reading an author-supplied manifest — should keep using
``json.load`` directly. This module is for Carton's own state.
"""

import json
import os
import time


__all__ = [
    "write_json_atomic",
    "read_json_quarantining",
    "quarantine_path_for",
]


def write_json_atomic(path, data, trailing_newline=False):
    """Serialise ``data`` to ``path`` via a temp file + atomic replace.

    Parent directories are created as needed. ``trailing_newline`` appends
    a final ``\\n`` for files that are expected to be human-edited or
    diffed (profiles), matching the previous hand-rolled writers.

    The temp file lives next to the target so ``os.replace`` stays within
    one filesystem — the property that makes the swap atomic. A failure
    part-way through leaves the ``.tmp`` behind and the original intact,
    which is the outcome we want: the caller sees the exception and the
    previous state is still readable.
    """
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        if trailing_newline:
            f.write("\n")
    os.replace(tmp, path)


def quarantine_path_for(path):
    """Return a collision-free ``<path>.corrupt-<ms>`` sidecar name."""
    return "{}.corrupt-{}".format(path, int(time.time() * 1000))


def read_json_quarantining(path, default, what="", require_mapping=True):
    """Read JSON from ``path``; on corruption quarantine it and use ``default``.

    Returns ``(data, quarantined_path)``. ``quarantined_path`` is ``""``
    on the normal paths (file read cleanly, or file absent) and the path
    the damaged file was moved to when recovery kicked in.

    ``default`` is used as-is when the file is missing and as the
    fallback when it is unreadable, so callers should pass a freshly
    built object rather than a shared one.

    ``require_mapping`` (on by default — every state file Carton owns is
    a JSON object) treats a well-formed but wrong-shaped payload as
    corruption too. Otherwise a file that somehow ended up holding
    ``[]`` or ``null`` would sail past the parse and blow up further in
    with an AttributeError that says nothing about the real problem.

    ``what`` is a short noun for the log line ("config.json", "installed
    packages"). Recovery is logged at warning level because it is a
    silent data loss event from the user's point of view — they need to
    be able to find out why their catalogues disappeared.
    """
    if not path or not os.path.exists(path):
        return default, ""

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if require_mapping and not isinstance(data, dict):
            raise ValueError(
                "expected a JSON object, got {}".format(type(data).__name__))
        return data, ""
    except (OSError, ValueError) as e:
        from carton.core.log import get_logger
        log = get_logger()
        label = what or path
        quarantined = quarantine_path_for(path)
        try:
            os.replace(path, quarantined)
        except OSError as move_err:
            # Couldn't even move it aside (locked / read-only volume).
            # Still return the default so startup continues — but say so,
            # because the next write will overwrite the damaged file and
            # the recovery copy won't exist.
            log.warning(
                "%s is unreadable (%s) and could not be moved aside (%s) — "
                "continuing with defaults; the damaged file will be "
                "overwritten on the next save", label, e, move_err)
            return default, ""
        log.warning(
            "%s is unreadable (%s) — moved to %s and continuing with "
            "defaults", label, e, quarantined)
        return default, quarantined
