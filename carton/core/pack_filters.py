"""Shared exclusion rules for building a Carton package zip.

Both the GUI publisher (``_publisher_zip.create_zip``) and the CLI
``carton-maya package pack`` walk a source tree and drop the same set
of VCS / build / editor detritus before zipping. Centralising the lists
here keeps the two paths in lockstep.
"""

EXCLUDE_DIRS = {
    "__pycache__", ".git", ".svn", ".hg",
    "tests", "test", "dist", "build",
    ".vscode", ".idea",
}

EXCLUDE_FILES = {".gitignore", ".gitattributes", ".DS_Store", "Thumbs.db"}
