"""Carton CLI entry point.

Sub-modules wire one area each:

- ``_package_cmd`` — author-facing operations on a single package
  (lint, check, schema).
- ``_catalogue_cmd`` — catalogue maintenance (list, unpublish,
  migrate, id, schema).

Everything funnels through ``main`` here so ``carton-maya``
(the entry script) and ``python -m carton`` (still supported)
both land in the same parser.
"""

import argparse
import sys

from carton.cli._package_cmd import (
    register_package_subparser,
    dispatch_package,
)
from carton.cli._catalogue_cmd import (
    register_catalogue_subparser,
    dispatch_catalogue,
)


def main():
    # On Windows with cp932 (Japanese) locale, argparse help and any
    # non-ASCII output crashes with UnicodeEncodeError. Force UTF-8 so
    # modern terminals (Windows Terminal, PowerShell 7+) render correctly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="carton-maya",
        description="Carton - Maya package manager CLI",
    )
    sub = parser.add_subparsers(dest="command")

    register_package_subparser(sub)
    register_catalogue_subparser(sub)

    args = parser.parse_args()

    if args.command == "package":
        dispatch_package(args, parser)
    elif args.command == "catalogue":
        dispatch_catalogue(args, parser)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
