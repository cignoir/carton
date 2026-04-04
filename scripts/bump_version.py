"""Bump the version in package.json and carton/__init__.py.

Usage:
    python scripts/bump_version.py patch   # 0.1.8 -> 0.1.9
    python scripts/bump_version.py minor   # 0.1.8 -> 0.2.0
    python scripts/bump_version.py major   # 0.1.8 -> 1.0.0
    python scripts/bump_version.py 1.2.3   # set explicit version
"""

import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(__file__))
_PKG_PATH = os.path.join(_ROOT, "package.json")
_INIT_PATH = os.path.join(_ROOT, "carton", "__init__.py")


def _read():
    with open(_PKG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(data):
    with open(_PKG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _update_init(new_ver):
    with open(_INIT_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    content = re.sub(
        r'^__version__\s*=\s*"[^"]*"',
        '__version__ = "{}"'.format(new_ver),
        content,
        count=1,
        flags=re.MULTILINE,
    )
    with open(_INIT_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def bump(kind):
    data = _read()
    old = data["version"]
    parts = list(map(int, old.split(".")))

    if kind == "patch":
        parts[2] += 1
    elif kind == "minor":
        parts[1] += 1
        parts[2] = 0
    elif kind == "major":
        parts[0] += 1
        parts[1] = 0
        parts[2] = 0
    else:
        # Treat as explicit version string
        parts = list(map(int, kind.split(".")))

    new_ver = ".".join(map(str, parts))
    data["version"] = new_ver
    _write(data)
    _update_init(new_ver)
    print("{} -> {}".format(old, new_ver))
    return new_ver


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: bump_version.py <patch|minor|major|X.Y.Z>")
        sys.exit(1)
    bump(sys.argv[1])
