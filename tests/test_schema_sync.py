"""Guard against schema drift between schemas/ and carton/data/schemas/.

``schemas/`` (repo root) is the editable source of truth; ``carton/data/
schemas/`` is the wheel-bundled copy that ``bundled_schema_path()`` serves
at runtime. They diverged once in both directions (i18n description vs the
maya_module entry_point exemption), so this test pins them byte-identical.

To change a schema: edit ``schemas/<file>`` then copy it over
``carton/data/schemas/<file>``.
"""

import os

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SOURCE_DIR = os.path.join(_REPO_ROOT, "schemas")
_BUNDLED_DIR = os.path.join(_REPO_ROOT, "carton", "data", "schemas")


def _schema_files(directory):
    return sorted(
        name for name in os.listdir(directory)
        if name.endswith(".schema.json")
    )


def test_same_schema_file_set():
    """A schema added or removed on one side only is drift too."""
    assert _schema_files(_SOURCE_DIR) == _schema_files(_BUNDLED_DIR)


@pytest.mark.parametrize("filename", _schema_files(_SOURCE_DIR))
def test_bundled_schema_matches_source(filename):
    with open(os.path.join(_SOURCE_DIR, filename), "rb") as f:
        source = f.read()
    with open(os.path.join(_BUNDLED_DIR, filename), "rb") as f:
        bundled = f.read()
    assert source == bundled, (
        "{} has drifted — edit schemas/{} and copy it over "
        "carton/data/schemas/{}".format(filename, filename, filename)
    )
