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

The template substitution itself lives in
:mod:`carton.core.installer_artifact`, which is also what the in-Maya
"Build Installer" button calls. This script only adds what release
builds need on top of it: the version fan-out, the filename convention
and the ``carton-v<ver>.zip`` the self-updater downloads. Two builders
with their own copy of the substitution is exactly how the runtime one
came to miss the bootstrap tokens and emit installers that died with a
NameError on drop.
"""

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT_DIR, "dist")

# Make `import carton...` resolve to this checkout rather than to any
# pip-installed copy, so a release build ships the code being released.
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from carton.core import installer_artifact  # noqa: E402

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


def _profile_name(profile_path):
    """Derive the seeded profile's name from its filename."""
    if not profile_path:
        return None
    base = os.path.basename(profile_path)
    if base.endswith(".json"):
        base = base[:-5]
    return base or None


def build(version=None, languages=None, profile_path=None, output=None):
    version = version or _detect_version()
    languages = languages or DEFAULT_LANGUAGES

    seed = _load_profile_seed(profile_path)
    profile_name = _profile_name(profile_path)

    os.makedirs(DIST_DIR, exist_ok=True)

    # The release zip the self-updater downloads. Same tree the
    # installers carry inline, written out once as its own asset.
    release_zip = os.path.join(DIST_DIR, "carton-v{}.zip".format(version))
    with open(release_zip, "wb") as f:
        f.write(installer_artifact.carton_zip_bytes())

    release_kb = os.path.getsize(release_zip) / 1024
    print("Carton v{}".format(version))
    print("  zip: {:.1f} KB  ({})".format(release_kb, os.path.basename(release_zip)))
    if seed is not None:
        print("  profile: {} ({} catalogues)".format(
            os.path.basename(profile_path), len(seed.get("catalogues", [])),
        ))

    # Output mode A: explicit --output → single file, language taken
    # from the profile if it sets one, otherwise "auto".
    if output:
        lang = (seed or {}).get("language", "auto")
        out_path = installer_artifact.build_one(
            output, version=version, seed=seed, language=lang,
            profile_name=profile_name,
        )
        out_kb = os.path.getsize(out_path) / 1024
        print("  {:>2}: {:.1f} KB  ({})".format(lang, out_kb, out_path))
        return

    # Output mode B: default fan-out, one installer per language variant.
    for lang in languages:
        out_name = _installer_filename(version, lang)
        out_path = installer_artifact.build_one(
            os.path.join(DIST_DIR, out_name), version=version, seed=seed,
            language=lang, profile_name=profile_name,
        )
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
