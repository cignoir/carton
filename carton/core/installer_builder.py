"""Self-contained installer builder usable from both dev and runtime.

The dev script ``scripts/build_installer.py`` and the in-Maya "Build
Installer" button in the Profile Manager both delegate here. The
function only depends on:

  * the live ``carton`` package directory (located via
    ``os.path.dirname(carton.__file__)``)
  * ``carton/data/install_carton.template.py`` shipped inside that
    package
  * an output path

…so it works exactly the same whether invoked from a clone of the
source repo or from a deployed Carton install with no source tree
beside it.
"""

import base64
import io
import os
import zipfile

import carton

_EXCLUDE_DIRS = {"__pycache__", ".git", ".svn", ".idea", ".vscode"}
SEED_TOKEN = "__SEED_CONFIG_JSON__"


def _carton_pkg_dir():
    return os.path.dirname(os.path.abspath(carton.__file__))


def _template_path():
    return os.path.join(_carton_pkg_dir(), "data", "install_carton.template.py")


def _zip_carton_to_bytes():
    """Bundle the live ``carton/`` package into an in-memory zip blob.

    Arcnames are made relative to the *parent* of carton/ so the layout
    inside the zip stays ``carton/...`` — exactly what the bootstrap
    template expects to extract.
    """
    pkg_dir = _carton_pkg_dir()
    parent = os.path.dirname(pkg_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(pkg_dir):
            dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                fp = os.path.join(root, f)
                arcname = os.path.relpath(fp, parent)
                zf.write(fp, arcname)
    return buf.getvalue()


def build_one(output_path, version=None, seed=None, language="auto"):
    """Build a single installer .py to ``output_path``.

    Args:
        output_path: Where to write the generated installer.
        version: Version string to embed. Defaults to ``carton.__version__``.
        seed: Optional dict (an :class:`InstallerProfile` ``to_dict``)
            embedded as the first-install seed config. ``None`` produces
            a vanilla installer.
        language: Language code embedded in the installer (``auto`` /
            ``ja`` / ``en``). Profiles that set ``language`` win over
            this argument unless the caller already merged them.

    Returns the absolute output path.
    """
    if version is None:
        version = getattr(carton, "__version__", "0.0.0")
    output_path = os.path.abspath(output_path)
    out_dir = os.path.dirname(output_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    # 1. Zip the live carton/ package in memory
    b64 = base64.b64encode(_zip_carton_to_bytes()).decode("ascii")

    # 2. Read template + substitute placeholders
    tpl_path = _template_path()
    if not os.path.exists(tpl_path):
        raise RuntimeError(
            "Installer template not found at {}. The carton/data/ directory"
            " was not deployed with this install.".format(tpl_path)
        )
    with open(tpl_path, "r", encoding="utf-8") as f:
        template = f.read()
    seed_literal = repr(seed) if seed is not None else "None"
    installer = (
        template
        .replace("__VERSION__", version)
        .replace("__CARTON_ZIP_B64__", b64)
        .replace(SEED_TOKEN, seed_literal)
        .replace("__LANGUAGE__", language)
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(installer)
    return output_path


def build_from_profile(profile_path, output_path, version=None):
    """Convenience for the runtime UI: read a profile JSON and build."""
    from carton.core.profile import InstallerProfile
    profile = InstallerProfile.load(profile_path)
    seed = profile.to_dict()
    language = seed.get("language", "auto")
    return build_one(
        output_path, version=version, seed=seed, language=language,
    )
