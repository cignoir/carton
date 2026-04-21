"""Icon file handling for catalogue publishing.

A package's ``icon`` field can be an emoji, the literal ``"@auto"``, a bare
filename, or an absolute path to an image file. When publishing, absolute
paths get copied into the catalogue's ``icons/`` directory and replaced
with just the basename in the stored metadata, so the catalogue is
self-contained.

These helpers are pure functions (no state) and used only by the
publisher — they live in their own module so publisher.py can stay
focused on the publish flow itself.
"""

import os
import shutil
import zipfile


def is_icon_file(icon):
    """True if ``icon`` is an absolute path to an existing image file."""
    return (isinstance(icon, str)
            and icon.endswith((".png", ".jpg", ".svg"))
            and os.path.isabs(icon)
            and os.path.exists(icon))


def normalise_icon_for_storage(icon):
    """Coerce an icon value into the on-disk shape (string | None).

    * Empty string / None → ``None`` (omit field).
    * Absolute image path → basename (the file gets copied separately
      via :func:`copy_icon_to_catalogue`).
    * Anything else (emoji, ``"@auto"``, bare filename) → as-is.
    """
    if icon is None or icon == "":
        return None
    if is_icon_file(icon):
        return os.path.basename(icon)
    return icon


def copy_icon_to_catalogue(icon_path, dest_filename, catalogue_base):
    """Copy an icon file into the catalogue's ``icons/`` directory verbatim.

    ``dest_filename`` is the basename to use in the catalogue. Passing
    the original basename preserves the author's filename instead of
    forcing ``<name>.png``.
    """
    icons_dir = os.path.join(catalogue_base, "icons")
    os.makedirs(icons_dir, exist_ok=True)
    dest = os.path.join(icons_dir, dest_filename)
    shutil.copy2(icon_path, dest)


def rebuild_icons_archive(catalogue_base):
    """Rebuild ``icons.zip`` from all PNGs in the catalogue's icons directory.

    No-op if the directory doesn't exist or has no PNGs.
    """
    icons_dir = os.path.join(catalogue_base, "icons")
    if not os.path.isdir(icons_dir):
        return
    pngs = [f for f in os.listdir(icons_dir) if f.lower().endswith(".png")]
    if not pngs:
        return
    archive_path = os.path.join(catalogue_base, "icons.zip")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for png in pngs:
            zf.write(os.path.join(icons_dir, png), png)
