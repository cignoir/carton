"""Build the Carton drag-and-drop installer.

Usage:
    python scripts/build_installer.py
    python scripts/build_installer.py --version 1.2.3
    python scripts/build_installer.py --lang ja en
"""

import argparse
import base64
import json
import os
import zipfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARTON_DIR = os.path.join(ROOT_DIR, "carton")
TEMPLATE_PATH = os.path.join(ROOT_DIR, "installer", "install_carton.template.py")
DIST_DIR = os.path.join(ROOT_DIR, "dist")

_EXCLUDE_DIRS = {"__pycache__", ".git", ".svn", ".idea", ".vscode"}

# Language variants to build by default
DEFAULT_LANGUAGES = ["auto", "ja", "en"]


def _detect_version():
    """Read version from package.json."""
    pkg_path = os.path.join(ROOT_DIR, "package.json")
    if os.path.exists(pkg_path):
        with open(pkg_path, "r", encoding="utf-8") as f:
            return json.load(f).get("version", "0.1.0")
    return "0.1.0"


def _installer_filename(version, lang):
    """Generate installer filename.

    auto  -> install_carton_v0-1-0.py
    ja    -> install_carton_ja_v0-1-0.py
    en    -> install_carton_en_v0-1-0.py
    """
    safe_ver = version.replace(".", "-")
    if lang == "auto":
        return "install_carton_v{}.py".format(safe_ver)
    return "install_carton_{}_v{}.py".format(lang, safe_ver)


def build(version=None, languages=None):
    version = version or _detect_version()
    languages = languages or DEFAULT_LANGUAGES

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

    # 3. Rename zip for release (used by self-updater)
    release_zip = os.path.join(DIST_DIR, "carton-v{}.zip".format(version.replace(".", "-")))
    os.replace(zip_path, release_zip)

    # 4. Read template
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    base = template.replace("__VERSION__", version).replace("__CARTON_ZIP_B64__", b64)

    # 5. Generate one installer per language
    release_kb = os.path.getsize(release_zip) / 1024
    print("Carton v{}".format(version))
    print("  zip: {:.1f} KB  ({})".format(release_kb, os.path.basename(release_zip)))
    for lang in languages:
        installer = base.replace("__LANGUAGE__", lang)
        out_name = _installer_filename(version, lang)
        out_path = os.path.join(DIST_DIR, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(installer)
        out_kb = os.path.getsize(out_path) / 1024
        print("  {:>2}: {:.1f} KB  ({})".format(lang, out_kb, out_name))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Carton installer")
    parser.add_argument("--version", help="Override version (default: from package.json)")
    parser.add_argument("--lang", nargs="*",
                        help="Language variants to build (default: auto ja en)")
    args = parser.parse_args()
    build(version=args.version, languages=args.lang)
