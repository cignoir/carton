"""Carton CLI — admin commands for catalogue management."""

import argparse
import json
import os
import sys


def _load_catalogue(path, migrate=True):
    """Load a catalogue file and return ``(catalogue_dict, normalized_path)``.

    By default v4.0 registries are migrated in-memory to the v5.0 shape
    so consumers only need to think in catalogue terms. Pass
    ``migrate=False`` to inspect the on-disk shape verbatim (used by
    the ``catalogue id`` command, which needs to reject pre-v5.0 files
    rather than silently upgrading them).
    """
    path = os.path.normpath(path)
    if not os.path.exists(path):
        print("Error: catalogue not found: {}".format(path))
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if migrate:
        from carton.core.migrations import migrate_registry_to_catalogue
        data, _ = migrate_registry_to_catalogue(data, stamp_id=False)
    return data, path


def _list_packages(args):
    """List all packages in a catalogue."""
    catalogue, _ = _load_catalogue(args.catalogue)
    packages = catalogue.get("packages", {})
    if not packages:
        print("No packages in catalogue.")
        return
    for pkg_id, pkg_data in packages.items():
        name = pkg_data.get("display_name", pkg_data.get("name", "?"))
        origin = pkg_data.get("origin") or {}
        latest = origin.get("latest_version", "?")
        print("  {} — {} v{}".format(pkg_id, name, latest))


def _unpublish(args):
    """Force-unpublish a package from a catalogue."""
    from carton.core.config import CatalogueEntry
    from carton.core.config import Config
    from carton.core.publisher import Publisher

    cat_entry = CatalogueEntry(path=args.catalogue, display_name="cli")
    config = Config(catalogues=[cat_entry])
    publisher = Publisher(config)

    # Show package info before unpublishing
    catalogue, _ = _load_catalogue(args.catalogue)
    packages = catalogue.get("packages", {})
    if args.id not in packages:
        print("Error: package {} not found in catalogue.".format(args.id))
        sys.exit(1)

    pkg = packages[args.id]
    display = pkg.get("display_name", pkg.get("name", args.id))
    origin = pkg.get("origin") or {}
    versions = list((origin.get("versions") or {}).keys())

    print("Package: {} ({})".format(display, args.id))
    print("Versions: {}".format(", ".join(versions) if versions else "none"))

    if not args.force:
        answer = input("Unpublish this package? [y/N] ")
        if answer.lower() not in ("y", "yes"):
            print("Cancelled.")
            return

    result = publisher.unpublish(args.id, cat_entry)
    print("Unpublished: {}".format(result["name"]))


def _catalogue_id(args):
    """Show or stamp a v5.0 catalogue's ``catalogue_id``.

    Vendor-neutral: only reads/writes the local catalogue.json. Refuses
    pre-v5.0 files so admins don't silently lose the schema bump — they
    should run ``catalogue migrate`` first.
    """
    from carton.core.uuid_id import is_valid_uuid, new_uuid
    from carton.core.migrations import CATALOGUE_SCHEMA_VERSION

    catalogue, path = _load_catalogue(args.path, migrate=False)
    if catalogue.get("schema_version") != CATALOGUE_SCHEMA_VERSION:
        print(
            "Error: not a v{} catalogue. Run "
            "'python -m carton catalogue migrate {}' first.".format(
                CATALOGUE_SCHEMA_VERSION, path,
            )
        )
        sys.exit(1)
    raw = (catalogue.get("catalogue_id") or "").strip().lower()
    current = raw if is_valid_uuid(raw) else ""
    if args.stamp:
        if current:
            print("Already has catalogue_id: {}".format(current))
            return
        new_id = new_uuid()
        catalogue["catalogue_id"] = new_id
        with open(path, "w", encoding="utf-8") as f:
            json.dump(catalogue, f, indent=2, ensure_ascii=False)
        print("Stamped: {}".format(new_id))
        return
    if current:
        print(current)
    else:
        print("(no catalogue_id)")
        sys.exit(2)


def _catalogue_migrate(args):
    """Migrate a v4.0 registry.json on disk to a v5.0 catalogue.json.

    Idempotent — running against an already-migrated tree is a no-op
    (and prints a hint pointing at the existing catalogue.json).
    """
    from carton.core.migrations import (
        CATALOGUE_FILENAME,
        LEGACY_REGISTRY_FILENAME,
        migrate_local_registry_file_to_catalogue,
    )

    target = os.path.abspath(args.path)
    if os.path.isdir(target):
        candidate = os.path.join(target, LEGACY_REGISTRY_FILENAME)
        if not os.path.exists(candidate):
            candidate = os.path.join(target, CATALOGUE_FILENAME)
        target = candidate

    if not os.path.exists(target):
        print("Error: file not found: {}".format(target))
        sys.exit(1)

    out_path = migrate_local_registry_file_to_catalogue(target)
    if not out_path:
        print("Nothing to migrate.")
        return
    print("Wrote: {}".format(out_path))
    if os.path.basename(target).lower() == LEGACY_REGISTRY_FILENAME and not os.path.exists(target):
        print("Backed up legacy registry.json next to it (look for '*.bak-v0.4.*').")


def main():
    parser = argparse.ArgumentParser(
        prog="carton",
        description="Carton — Maya package manager CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # list
    ls = sub.add_parser("list", help="List packages in a catalogue")
    ls.add_argument("catalogue", help="Path to catalogue.json")

    # unpublish
    unpub = sub.add_parser("unpublish", help="Force-unpublish a package")
    unpub.add_argument("--catalogue", required=True, help="Path to catalogue.json")
    unpub.add_argument("--id", required=True,
                       help="Package id to unpublish ('namespace/name')")
    unpub.add_argument("--force", "-f", action="store_true",
                       help="Skip confirmation prompt")

    # catalogue subgroup (v5.0)
    cat = sub.add_parser("catalogue", help="Catalogue (v5.0) utilities")
    cat_sub = cat.add_subparsers(dest="catalogue_command")
    mig_p = cat_sub.add_parser(
        "migrate",
        help="Convert a v4.0 registry.json into a v5.0 catalogue.json in place",
    )
    mig_p.add_argument(
        "path",
        help="Path to registry.json (or its containing directory)",
    )
    cid_p = cat_sub.add_parser(
        "id",
        help="Print or stamp a v5.0 catalogue's catalogue_id (UUID)",
    )
    cid_p.add_argument("path", help="Path to catalogue.json")
    cid_p.add_argument(
        "--stamp", action="store_true",
        help="Write a fresh UUID into the file if it doesn't already have one",
    )

    args = parser.parse_args()

    if args.command == "list":
        _list_packages(args)
    elif args.command == "unpublish":
        _unpublish(args)
    elif args.command == "catalogue" and getattr(args, "catalogue_command", None) == "migrate":
        _catalogue_migrate(args)
    elif args.command == "catalogue" and getattr(args, "catalogue_command", None) == "id":
        _catalogue_id(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
