"""LRU-style size cap for the remote icon cache.

The icon cache accumulates one PNG per package the user has ever seen in
a remote registry. Without a cap it grows forever. This module provides
a single function that keeps total on-disk size under a soft limit,
evicting the least-recently-used files first.

"LRU" here is approximated with the filesystem's ``st_atime``. On modern
Windows and Linux, atime updates are typically debounced but still
monotonic-enough for cache eviction purposes. If a file has never been
read since it was written, ``st_mtime`` provides a sensible fallback.
"""

import os

# Default cap: 50 MiB. Chosen to comfortably hold a few hundred icons at
# typical registry sizes without becoming noticeable on disk.
_DEFAULT_MAX_BYTES = 50 * 1024 * 1024


def _entries(cache_dir):
    """Yield ``(path, size, last_used)`` tuples for every cached file."""
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        last_used = max(st.st_atime, st.st_mtime)
        yield path, st.st_size, last_used


def enforce_size_limit(cache_dir, max_bytes=_DEFAULT_MAX_BYTES):
    """Evict least-recently-used files until total size is under the limit.

    Safe to call on a non-existent directory (it's a no-op). Best-effort:
    individual delete failures are swallowed so a single locked file
    doesn't prevent trimming the rest.

    Args:
        cache_dir: Path to the icon cache directory.
        max_bytes: Target upper bound in bytes. When the cache grows past
            this, the oldest entries are deleted until it fits.

    Returns:
        Number of files removed.
    """
    if not cache_dir or not os.path.isdir(cache_dir):
        return 0

    files = list(_entries(cache_dir))
    total = sum(size for _, size, _ in files)
    if total <= max_bytes:
        return 0

    # Oldest first.
    files.sort(key=lambda x: x[2])
    removed = 0
    for path, size, _ in files:
        if total <= max_bytes:
            break
        try:
            os.remove(path)
            total -= size
            removed += 1
        except OSError:
            continue
    return removed
