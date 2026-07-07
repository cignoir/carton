"""Pin the version number identical across every file that declares it.

carton/__init__.py, pyproject.toml and package.json each carry the
version. The release workflow rewrites them from the git tag, but manual
bumps have historically updated only one file (0.5.8 in __init__.py vs
0.5.6 left in pyproject.toml), shipping wheels whose metadata disagrees
with the runtime banner. This test makes a partial bump fail CI.
"""

import json
import os
import re

import carton

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _pyproject_version():
    with open(os.path.join(_ROOT, "pyproject.toml"), encoding="utf-8") as f:
        m = re.search(r'^version = "([^"]+)"$', f.read(), re.MULTILINE)
    assert m, "no version field found in pyproject.toml"
    return m.group(1)


def _package_json_version():
    with open(os.path.join(_ROOT, "package.json"), encoding="utf-8") as f:
        return json.load(f)["version"]


def test_versions_are_in_sync():
    assert carton.__version__ == _pyproject_version() == _package_json_version()
