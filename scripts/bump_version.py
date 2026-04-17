"""Bump the version in package.json and carton/__init__.py.

Usage:
    python scripts/bump_version.py patch              # 0.1.8 -> 0.1.9
    python scripts/bump_version.py minor              # 0.1.8 -> 0.2.0
    python scripts/bump_version.py major              # 0.1.8 -> 1.0.0
    python scripts/bump_version.py 1.2.3              # set explicit version

    # Stage and commit the bump with a Conventional Commits message
    # (chore(release): bump version to X.Y.Z), and optionally tag it.
    python scripts/bump_version.py patch --commit
    python scripts/bump_version.py patch --commit --tag
"""

import json
import os
import re
import subprocess
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


def _git(*args):
    subprocess.run(["git", *args], cwd=_ROOT, check=True)


def commit_bump(new_ver, tag=False):
    """Stage the bumped files and create a Conventional Commits release commit."""
    _git("add", _PKG_PATH, _INIT_PATH)
    msg = "chore(release): bump version to {}".format(new_ver)
    _git("commit", "-m", msg)
    if tag:
        _git("tag", "-a", "v{}".format(new_ver), "-m", "v{}".format(new_ver))
    print("committed: {}".format(msg))


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: bump_version.py <patch|minor|major|X.Y.Z> [--commit] [--tag]")
        sys.exit(1)

    do_commit = "--commit" in args
    do_tag = "--tag" in args
    positional = [a for a in args if not a.startswith("--")]
    if not positional:
        print("Usage: bump_version.py <patch|minor|major|X.Y.Z> [--commit] [--tag]")
        sys.exit(1)

    new_ver = bump(positional[0])
    if do_commit or do_tag:
        commit_bump(new_ver, tag=do_tag)
