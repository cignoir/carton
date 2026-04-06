"""Sidecar metadata helpers for single-file scripts.

A sidecar is a JSON file placed next to a single-file script, named
``<filename-with-ext>.carton.json``. It carries the same shape as a folder
package's ``package.json`` (namespace, name, version, entry_point, etc.).

Folder packages keep using ``package.json``; this module exists only for the
single-file case where we have nowhere else to put the metadata.
"""

import json
import os


SIDECAR_SUFFIX = ".carton.json"


def sidecar_path_for(file_path):
    """Return the sidecar path for a single-file script.

    Example: ``foo/bar.mel`` -> ``foo/bar.mel.carton.json``
    """
    return file_path + SIDECAR_SUFFIX


def read_sidecar(file_path):
    """Read the sidecar next to a single-file script.

    Returns the parsed dict, or ``None`` if the sidecar does not exist or is
    unreadable.
    """
    path = sidecar_path_for(file_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_sidecar(file_path, data):
    """Write/overwrite the sidecar next to a single-file script."""
    path = sidecar_path_for(file_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def merge_sidecar(file_path, updates):
    """Read the existing sidecar (if any), merge ``updates`` in, write back.

    Returns the merged dict that was written.
    """
    data = read_sidecar(file_path) or {}
    data.update(updates)
    write_sidecar(file_path, data)
    return data
