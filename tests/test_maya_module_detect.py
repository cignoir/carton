"""Tests for Maya module detection / parsing."""

import os
import tempfile

from carton.core.maya_module_detect import (
    is_maya_module,
    parse_mod_file,
    parse_package_contents,
    detect,
)


_PACKAGE_CONTENTS_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0.0"
    Name="SiWeightEditor"
    AppVersion="1.0.0">
  <Components>
    <ComponentEntry ModuleName="./scripts/userSetup.py" />
  </Components>
</ApplicationPackage>
"""

_MOD_FILE = """\
# A simple Maya module
+ MyMod 1.2.3 .
scripts: scripts
plug-ins: plug-ins
icons: icons
"""


def _make_pkg_contents_dir(tmp):
    folder = os.path.join(tmp, "SIWeightEditor")
    os.makedirs(os.path.join(folder, "Contents", "scripts"))
    with open(os.path.join(folder, "PackageContents.xml"), "w") as f:
        f.write(_PACKAGE_CONTENTS_XML)
    with open(os.path.join(folder, "Contents", "scripts", "userSetup.py"), "w") as f:
        f.write("# stub")
    return folder


def _make_mod_dir(tmp):
    folder = os.path.join(tmp, "MyMod")
    os.makedirs(os.path.join(folder, "scripts"))
    with open(os.path.join(folder, "MyMod.mod"), "w") as f:
        f.write(_MOD_FILE)
    return folder


def test_is_maya_module_with_package_contents():
    with tempfile.TemporaryDirectory() as tmp:
        assert is_maya_module(_make_pkg_contents_dir(tmp))


def test_is_maya_module_with_mod_file():
    with tempfile.TemporaryDirectory() as tmp:
        assert is_maya_module(_make_mod_dir(tmp))


def test_is_maya_module_plain_folder():
    with tempfile.TemporaryDirectory() as tmp:
        plain = os.path.join(tmp, "plain")
        os.makedirs(plain)
        with open(os.path.join(plain, "script.py"), "w") as f:
            f.write("def show(): pass\n")
        assert not is_maya_module(plain)


def test_parse_package_contents_extracts_name_and_user_setup():
    with tempfile.TemporaryDirectory() as tmp:
        folder = _make_pkg_contents_dir(tmp)
        parsed = parse_package_contents(os.path.join(folder, "PackageContents.xml"))
        assert parsed["name"] == "SiWeightEditor"
        assert parsed["user_setup"] == "scripts/userSetup.py"


def test_parse_mod_file_extracts_overrides():
    with tempfile.TemporaryDirectory() as tmp:
        folder = _make_mod_dir(tmp)
        parsed = parse_mod_file(os.path.join(folder, "MyMod.mod"))
        assert parsed["name"] == "MyMod"
        assert parsed["version"] == "1.2.3"
        assert parsed["scripts"] == "scripts"
        assert parsed["plug_ins"] == "plug-ins"
        assert parsed["icons"] == "icons"


def test_detect_returns_module_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        folder = _make_pkg_contents_dir(tmp)
        info = detect(folder)
        assert info["is_module"] is True
        assert info["name"] == "SiWeightEditor"
        assert info["user_setup"] == "scripts/userSetup.py"
