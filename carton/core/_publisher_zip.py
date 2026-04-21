"""Zip-building helper for the publisher.

Extracted from ``publisher.py`` so the artifact-creation step — walk the
source, drop build detritus, inject the canonical ``package.json`` — can
be reasoned about (and tested) without instantiating a full
:class:`~carton.core.publisher.Publisher`.
"""

import json
import os
import zipfile

from carton.core.catalogue_icons import normalise_icon_for_storage


_DEFAULT_MAYA_VERSIONS = ["2024", "2025", "2026", "2027"]

_EXCLUDE_DIRS = {
    "__pycache__", ".git", ".svn", ".hg",
    "tests", "test", "dist", "build",
    ".vscode", ".idea",
}
_EXCLUDE_FILES = {".gitignore", ".gitattributes", ".DS_Store", "Thumbs.db"}


def create_zip(staging_dir, local_path, namespace, name, version, is_folder,
               entry_point, display_name, icon, description, pkg_type, author,
               maya_versions=None,
               home_origin=None,
               include_compiled=False,
               embed_source_path=True):
    """Create a ``<name>-<version>.zip`` inside ``staging_dir``.

    Walks the source tree (for folder-mode packages) dropping VCS /
    build / test directories, strips ``.pyc`` that have a ``.py``
    sibling unless ``include_compiled`` forces them in, and injects a
    canonical ``package.json`` at the archive root. File-mode packages
    are a single-file zip. Returns the absolute path to the created zip.
    """
    os.makedirs(staging_dir, exist_ok=True)
    zip_path = os.path.join(staging_dir, "{}-{}.zip".format(name, version))

    pkg_json = {
        "namespace": namespace,
        "name": name,
        "display_name": display_name,
        "version": version,
        "type": pkg_type,
        "description": description,
        "author": author,
        "maya_versions": list(maya_versions) if maya_versions else list(_DEFAULT_MAYA_VERSIONS),
        "entry_point": entry_point,
        "icon": normalise_icon_for_storage(icon),
    }
    if embed_source_path:
        # Absolute path of the source files at publish time. The
        # installer uses this to auto-relink My Tools entries when
        # the same user reinstalls Carton on a machine that still
        # has the original sources at this path. Opt-out for public
        # catalogues where leaking the publisher's directory layout
        # is undesirable.
        pkg_json["source_path"] = os.path.abspath(local_path)
    if home_origin:
        pkg_json["home_origin"] = home_origin

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if is_folder:
            for root, dirs, files in os.walk(local_path):
                dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
                file_set = set(files)
                for f in files:
                    # Strip .pyc that have a .py sibling — those are
                    # redundant build artifacts. Keep .pyc that ship
                    # standalone (legacy in-house tools without
                    # source). The ``include_compiled`` flag is now
                    # only an override that forces ALL .pyc to be
                    # kept regardless.
                    if f.endswith(".pyc"):
                        sibling_py = f[:-1]  # foo.pyc -> foo.py
                        if sibling_py in file_set and not include_compiled:
                            continue
                    if f in _EXCLUDE_FILES:
                        continue
                    # Skip stale package.json — we'll inject the canonical one
                    if f == "package.json" and root == local_path:
                        continue
                    fp = os.path.join(root, f)
                    arcname = os.path.relpath(fp, local_path)
                    zf.write(fp, arcname)
            zf.writestr("package.json",
                        json.dumps(pkg_json, indent=2, ensure_ascii=False))
        else:
            zf.write(local_path, os.path.basename(local_path))
            zf.writestr("package.json",
                        json.dumps(pkg_json, indent=2, ensure_ascii=False))

    return zip_path
