"""Build the Carton drag-and-drop installer.

Usage:
    # Default build — produces install_carton_{auto,ja,en}_v<ver>.py
    python scripts/build_installer.py

    # Override version or language list
    python scripts/build_installer.py --version 1.2.3
    python scripts/build_installer.py --lang ja en

    # Build a customized installer that pre-seeds config.json on first
    # install with the values from a profile JSON file. Outputs a single
    # installer (the language list is ignored if --output is given).
    python scripts/build_installer.py \\
        --profile path/to/studio.json \\
        --output dist/install_carton_studio.py
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

# Make `import carton.core.profile` work when this script is run directly
# without an editable install of the package.
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

_EXCLUDE_DIRS = {"__pycache__", ".git", ".svn", ".idea", ".vscode"}

# Language variants to build by default
DEFAULT_LANGUAGES = ["auto", "ja", "en"]

# Token in the template that gets replaced with the JSON-encoded seed
# config (or "null" when no profile is supplied).
SEED_TOKEN = "__SEED_CONFIG_JSON__"


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


def _load_profile_seed(profile_path):
    """Load and validate a profile JSON, return its dict form.

    Returns ``None`` if no profile path was given. Raises whatever
    InstallerProfile.load raises on validation errors so the CLI surfaces
    a useful message.
    """
    if not profile_path:
        return None
    from carton.core.profile import InstallerProfile
    profile = InstallerProfile.load(profile_path)
    return profile.to_dict()


def build(version=None, languages=None, profile_path=None, output=None):
    version = version or _detect_version()
    languages = languages or DEFAULT_LANGUAGES

    seed = _load_profile_seed(profile_path)
    # The token in the template is substituted as a Python literal so the
    # generated installer can be `import`-loaded without a runtime parse.
    # repr() handles dict / list / str / bool / None cleanly for our
    # field types and emits ``True`` / ``False`` / ``None`` (not the JSON
    # ``true`` / ``false`` / ``null``).
    seed_literal = repr(seed) if seed is not None else "None"

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
    release_zip = os.path.join(DIST_DIR, "carton-v{}.zip".format(version))
    os.replace(zip_path, release_zip)

    # 4. Read template and substitute the static placeholders.
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    base = (
        template
        .replace("__VERSION__", version)
        .replace("__CARTON_ZIP_B64__", b64)
        .replace(SEED_TOKEN, seed_literal)
    )

    release_kb = os.path.getsize(release_zip) / 1024
    print("Carton v{}".format(version))
    print("  zip: {:.1f} KB  ({})".format(release_kb, os.path.basename(release_zip)))
    if seed is not None:
        print("  profile: {} ({} registries)".format(
            os.path.basename(profile_path), len(seed.get("registries", [])),
        ))

    # 5. Output mode A: explicit --output → single file, language taken
    # from the profile if it sets one, otherwise "auto".
    if output:
        lang = (seed or {}).get("language", "auto")
        installer = base.replace("__LANGUAGE__", lang)
        out_path = os.path.abspath(output)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(installer)
        out_kb = os.path.getsize(out_path) / 1024
        print("  {:>2}: {:.1f} KB  ({})".format(lang, out_kb, out_path))
        return

    # Output mode B: default fan-out, one installer per language variant.
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
    parser.add_argument("--profile",
                        help="Path to a profile JSON whose values will be "
                             "embedded as the first-install seed config")
    parser.add_argument("-o", "--output",
                        help="Output file path (single-installer mode). "
                             "When set, only one installer is produced.")
    args = parser.parse_args()
    build(
        version=args.version,
        languages=args.lang,
        profile_path=args.profile,
        output=args.output,
    )
