"""Bump the version in package.json.

Usage:
    python scripts/bump_version.py patch   # 0.1.8 -> 0.1.9
    python scripts/bump_version.py minor   # 0.1.8 -> 0.2.0
    python scripts/bump_version.py major   # 0.1.8 -> 1.0.0
    python scripts/bump_version.py 1.2.3   # set explicit version
"""

import json
import os
import sys

_PKG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "package.json")


def _read():
    with open(_PKG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(data):
    with open(_PKG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


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
    print("{} -> {}".format(old, new_ver))
    return new_ver


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: bump_version.py <patch|minor|major|X.Y.Z>")
        sys.exit(1)
    bump(sys.argv[1])
