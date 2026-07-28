"""Age-based sweep of Carton's staging directories.

Staging holds zips in transit: package downloads on their way into
``packages/``, freshly built artifacts on their way into a catalogue,
and Carton's own staged self-update. Every one of those has a step that
consumes the file and deletes it — but only on the paths that succeed.

A download that fails to install, a GitHub publish whose release upload
the user never completed, an update staged and then superseded by a
newer one: each leaves a zip nobody will ever look at again, in a
directory nothing ever swept. On a flaky connection that grows without
bound.

Rather than teach every failure path to clean up after itself (the
GitHub publish flow genuinely needs its zip to outlive the call — the
manual instructions point at it), staging is treated as a cache: files
that have not been touched in a while are gone.
"""

import os
import time


__all__ = ["sweep_staging", "DEFAULT_MAX_AGE_SECONDS"]


# A week. Long enough that a publish the user is part-way through
# finishing by hand survives a weekend, short enough that abandoned
# downloads don't accumulate across a project.
DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


def sweep_staging(staging_dir, max_age_seconds=DEFAULT_MAX_AGE_SECONDS,
                  keep=()):
    """Delete files in ``staging_dir`` older than ``max_age_seconds``.

    ``keep`` is a collection of absolute paths to spare regardless of
    age — the caller uses it for a staged update that has been recorded
    but not yet applied.

    Returns the number of files removed. Best-effort throughout: a
    locked file (antivirus, another Maya session mid-download) is
    skipped rather than raised, since sweeping a cache is never worth
    interrupting what the user was actually doing.
    """
    if not staging_dir or not os.path.isdir(staging_dir):
        return 0

    spared = {os.path.normcase(os.path.abspath(p)) for p in keep or ()}
    cutoff = time.time() - max_age_seconds
    removed = 0

    for name in os.listdir(staging_dir):
        path = os.path.join(staging_dir, name)
        if not os.path.isfile(path):
            continue
        if os.path.normcase(os.path.abspath(path)) in spared:
            continue
        try:
            if os.path.getmtime(path) >= cutoff:
                continue
            os.remove(path)
        except OSError:
            continue
        removed += 1

    return removed


def sweep_all(config, max_age_seconds=DEFAULT_MAX_AGE_SECONDS):
    """Sweep both staging directories Carton writes to.

    ``install_dir/.staging`` holds package downloads and publish
    artifacts. The bootstrap directory has its own ``.staging`` for
    self-updates, which lives outside install_dir so updates keep
    working when the user relocates their data directory.

    Called once from :func:`carton.startup`, after the bootstrap has
    already had its chance to apply any pending update — so a zip still
    sitting there is either the one recorded for a later restart (which
    we spare by name) or an orphan.
    """
    from carton.core.config import default_bootstrap_dir
    from carton.core.log import get_logger

    removed = sweep_staging(config.staging_dir, max_age_seconds)

    bootstrap_dir = default_bootstrap_dir()
    removed += sweep_staging(
        os.path.join(bootstrap_dir, ".staging"),
        max_age_seconds,
        keep=_pending_staged_zip(bootstrap_dir),
    )

    if removed:
        get_logger().info("swept %d stale file(s) from staging", removed)
    return removed


def _pending_staged_zip(bootstrap_dir):
    """Absolute path(s) of a staged update recorded but not yet applied."""
    import json

    path = os.path.join(bootstrap_dir, "pending_update.json")
    if not os.path.exists(path):
        return ()
    try:
        with open(path, "r", encoding="utf-8") as f:
            pending = json.load(f)
    except (OSError, ValueError):
        return ()
    if not isinstance(pending, dict):
        return ()
    rel = pending.get("staged_zip")
    if not rel:
        return ()
    return (os.path.join(bootstrap_dir, rel),)
