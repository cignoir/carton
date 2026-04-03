"""Build the Carton drag-and-drop installer.

Usage:
    python scripts/build_installer.py
    python scripts/build_installer.py --version 1.2.3
"""

import argparse
import base64
import json
import os
import sys
import zipfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARTON_DIR = os.path.join(ROOT_DIR, "carton")
TEMPLATE_PATH = os.path.join(ROOT_DIR, "installer", "install_carton.template.py")
DIST_DIR = os.path.join(ROOT_DIR, "dist")

_EXCLUDE_DIRS = {"__pycache__", ".git", ".svn", ".idea", ".vscode"}


def _detect_version():
    """Read version from package.json."""
    pkg_path = os.path.join(ROOT_DIR, "package.json")
    if os.path.exists(pkg_path):
        with open(pkg_path, "r", encoding="utf-8") as f:
            return json.load(f).get("version", "0.1.0")
    return "0.1.0"


def build(version=None):
    version = version or _detect_version()

    os.makedirs(DIST_DIR, exist_ok=True)
    zip_path = os.path.join(DIST_DIR, "carton.zip")

    # 1. Create zip
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(CARTON_DIR):
            dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                fp = os.path.join(root, f)
                arcname = os.path.relpath(fp, ROOT_DIR)
                zf.write(fp, arcname)

    # 2. Base64 encode
    with open(zip_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    # 3. Clean up intermediate zip
    os.remove(zip_path)

    # 4. Fill template
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    installer = template.replace("__VERSION__", version).replace("__CARTON_ZIP_B64__", b64)

    out_name = "install_carton_v{}.py".format(version)
    out_path = os.path.join(DIST_DIR, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(installer)

    out_kb = os.path.getsize(out_path) / 1024
    print("Carton v{}".format(version))
    print("  installer: {:.1f} KB  ({})".format(out_kb, out_path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Carton installer")
    parser.add_argument("--version", help="Override version (default: from package.json)")
    args = parser.parse_args()
    build(version=args.version)
