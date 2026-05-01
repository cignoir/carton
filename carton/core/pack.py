"""Build a Carton package zip from an on-disk source folder.

This is the CLI-facing companion to :mod:`carton.core._publisher_zip`.
The publisher path constructs ``package.json`` from GUI inputs and
injects it into the archive; the CLI ``carton-maya package pack`` path
treats the existing ``package.json`` on disk as the source of truth and
just zips the folder around it. The two paths share file-exclusion
rules via :mod:`carton.core.pack_filters`.

Lint runs first by default — a package that fails ``carton-maya
package check`` should not produce a publishable artifact.
"""

import json
import os
import zipfile

from carton.core.lint import lint_package
from carton.core.pack_filters import EXCLUDE_DIRS, EXCLUDE_FILES


class PackError(RuntimeError):
    """Raised when ``pack_package`` cannot produce an artifact."""


def pack_package(src_dir, out_dir="dist", validate=True, include_compiled=False):
    """Build ``<out_dir>/<name>-<version>.zip`` from ``src_dir``.

    ``src_dir`` must contain a ``package.json`` — that file's ``name``
    and ``version`` decide the archive filename and are written verbatim
    into the zip (no fields are rewritten). When ``validate`` is true
    (the default) the source is linted first and any errors raise
    :class:`PackError` before the zip is touched.

    Returns the absolute path to the created zip.
    """
    src_dir = os.path.abspath(src_dir)
    if not os.path.isdir(src_dir):
        raise PackError("not a directory: {}".format(src_dir))

    pkg_json_path = os.path.join(src_dir, "package.json")
    if not os.path.exists(pkg_json_path):
        raise PackError(
            "package.json not found at {}. "
            "Run `carton-maya package init` to scaffold one.".format(src_dir)
        )

    if validate:
        result = lint_package(src_dir)
        if result.has_errors():
            msg = "\n".join(
                "  {}: {}".format(i.rule, i.message) for i in result.errors
            )
            raise PackError("lint errors block packing:\n" + msg)

    try:
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            pkg = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise PackError("cannot read package.json: {}".format(exc))

    name = pkg.get("name")
    version = pkg.get("version")
    if not name or not version:
        raise PackError(
            "package.json is missing 'name' or 'version' — fix with "
            "`carton-maya package lint`."
        )

    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, "{}-{}.zip".format(name, version))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src_dir):
            # Don't descend into the output dir if it sits under src_dir
            if os.path.abspath(root) == out_dir:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            file_set = set(files)
            for f in files:
                if f.endswith(".pyc"):
                    sibling_py = f[:-1]
                    if sibling_py in file_set and not include_compiled:
                        continue
                if f in EXCLUDE_FILES:
                    continue
                fp = os.path.join(root, f)
                # Skip the artifact we're writing, in case a previous
                # run dropped it under src_dir
                if os.path.abspath(fp) == zip_path:
                    continue
                arcname = os.path.relpath(fp, src_dir)
                zf.write(fp, arcname)

    return zip_path
