"""Render a Carton package skeleton from a bundled template.

Templates live under ``carton/data/templates/<type>/`` and are walked
file-by-file:

* Filenames containing the literal ``__name__`` token are rewritten
  with the package name (so ``__name__/__init__.py`` becomes
  ``my_tool/__init__.py``).
* File contents have ``{{key}}`` placeholders substituted from the
  context dict (``name``, ``display_name``, ``version``,
  ``description``, ``author``, ``maya_versions_json``,
  ``platform_json``).

Empty placeholders are written as-is, so missing keys surface as
unsubstituted ``{{...}}`` in the generated package — caught quickly
by ``carton-maya package lint``.
"""

import json
import os
import shutil


PACKAGE_TYPES = ("python_package", "mel_script", "plugin", "maya_module")
DEFAULT_MAYA_VERSIONS = ("2024", "2025", "2026")
DEFAULT_PLATFORM = ("win64",)
NAME_TOKEN = "__name__"


class InitError(RuntimeError):
    """Raised when scaffolding cannot proceed."""


def template_root(pkg_type):
    """Absolute path to a bundled template tree, or raise ``InitError``."""
    if pkg_type not in PACKAGE_TYPES:
        raise InitError(
            "unknown package type: {!r} (expected one of {})".format(
                pkg_type, ", ".join(PACKAGE_TYPES)
            )
        )
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(here, "data", "templates", pkg_type)
    if not os.path.isdir(candidate):
        raise InitError(
            "bundled template not found: {} (carton-maya install is incomplete)".format(
                candidate
            )
        )
    return candidate


def build_context(name, display_name, version, description, author,
                  maya_versions, platform=None):
    """Assemble the substitution dict expected by templates."""
    ctx = {
        "name": name,
        "display_name": display_name,
        "version": version,
        "description": description,
        "author": author,
        "maya_versions_json": json.dumps(list(maya_versions)),
        "platform_json": json.dumps(list(platform or DEFAULT_PLATFORM)),
    }
    return ctx


def render_template(pkg_type, target_dir, context, force=False):
    """Copy ``carton/data/templates/<pkg_type>/`` into ``target_dir``.

    ``target_dir`` is created if absent. If it already contains files
    other than the ones we'd write, raise ``InitError`` unless
    ``force`` is true. Returns a list of created paths (for display).
    """
    src_root = template_root(pkg_type)
    target_dir = os.path.abspath(target_dir)

    if os.path.exists(target_dir) and os.listdir(target_dir) and not force:
        raise InitError(
            "target directory not empty: {} (use --force to overwrite)".format(
                target_dir
            )
        )
    os.makedirs(target_dir, exist_ok=True)

    written = []
    for root, dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        dst_root = target_dir if rel == "." else os.path.join(
            target_dir, _substitute_path(rel, context["name"])
        )
        os.makedirs(dst_root, exist_ok=True)

        for fname in files:
            src = os.path.join(root, fname)
            dst_name = _substitute_path(fname, context["name"])
            dst = os.path.join(dst_root, dst_name)
            _render_file(src, dst, context)
            written.append(dst)

    return written


def _substitute_path(path_part, name):
    """Replace ``__name__`` segments inside a path component with ``name``."""
    return path_part.replace(NAME_TOKEN, name)


def _render_file(src, dst, context):
    """Read template ``src``, substitute placeholders, write to ``dst``."""
    if _is_binary(src):
        shutil.copyfile(src, dst)
        return
    with open(src, "r", encoding="utf-8") as f:
        content = f.read()
    for key, value in context.items():
        content = content.replace("{{" + key + "}}", str(value))
    with open(dst, "w", encoding="utf-8") as f:
        f.write(content)


def _is_binary(path):
    """Heuristic: treat files with NUL bytes in their first 4 KB as binary."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
    except OSError:
        return False
    return b"\x00" in chunk
