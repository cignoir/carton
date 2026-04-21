"""Carton CLI — admin commands for registry management."""

import argparse
import json
import os
import sys


def _load_registry(path):
    """Load and return (registry_dict, normalized_path)."""
    path = os.path.normpath(path)
    if not os.path.exists(path):
        print("Error: registry not found: {}".format(path))
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f), path


def _list_packages(args):
    """List all packages in a registry."""
    registry, _ = _load_registry(args.registry)
    packages = registry.get("packages", {})
    if not packages:
        print("No packages in registry.")
        return
    for pkg_id, pkg_data in packages.items():
        name = pkg_data.get("display_name", pkg_data.get("name", "?"))
        latest = pkg_data.get("latest_version", "?")
        print("  {} — {} v{}".format(pkg_id, name, latest))


def _unpublish(args):
    """Force-unpublish a package from a registry."""
    from carton.core.config import RegistryEntry
    from carton.core.config import Config
    from carton.core.publisher import Publisher

    reg_entry = RegistryEntry(name="cli", path=args.registry)
    config = Config(registries=[reg_entry])
    publisher = Publisher(config)

    # Show package info before unpublishing
    registry, _ = _load_registry(args.registry)
    packages = registry.get("packages", {})
    if args.id not in packages:
        print("Error: package {} not found in registry.".format(args.id))
        sys.exit(1)

    pkg = packages[args.id]
    display = pkg.get("display_name", pkg.get("name", args.id))
    versions = list(pkg.get("versions", {}).keys())

    print("Package: {} ({})".format(display, args.id))
    print("Versions: {}".format(", ".join(versions) if versions else "none"))

    if not args.force:
        answer = input("Unpublish this package? [y/N] ")
        if answer.lower() not in ("y", "yes"):
            print("Cancelled.")
            return

    result = publisher.unpublish(args.id, reg_entry)
    print("Unpublished: {}".format(result["name"]))


def _registry_id(args):
    """Show or stamp a registry's ``registry_id``.

    Vendor-neutral: only reads/writes the local registry.json. Useful for
    admins migrating pre-UUID registries (e.g. ones already mirrored to a
    remote host) — stamp locally, then re-upload the file.
    """
    from carton.core.registry_id import (
        read_registry_id,
        stamp_registry_id,
    )

    from carton.core.migrations import REGISTRY_SCHEMA_VERSION, migrate_registry_data

    registry, path = _load_registry(args.registry)
    registry, _ = migrate_registry_data(registry)
    current = read_registry_id(registry)
    if args.stamp:
        rid, was_new = stamp_registry_id(registry)
        registry["schema_version"] = REGISTRY_SCHEMA_VERSION
        if was_new or current != rid:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)
            print("Stamped: {}".format(rid))
        else:
            print("Already has registry_id: {}".format(rid))
        return
    if current:
        print(current)
    else:
        print("(no registry_id)")
        sys.exit(2)


def _catalogue_id(args):
    """Show or stamp a v5.0 catalogue's ``catalogue_id``.

    Vendor-neutral: only reads/writes the local catalogue.json. Refuses
    pre-v5.0 files so admins don't silently lose the schema bump — they
    should run ``catalogue migrate`` first.
    """
    from carton.core.registry_id import is_valid_registry_id, new_registry_id
    from carton.core.migrations import CATALOGUE_SCHEMA_VERSION

    catalogue, path = _load_registry(args.path)
    if catalogue.get("schema_version") != CATALOGUE_SCHEMA_VERSION:
        print(
            "Error: not a v{} catalogue. Run "
            "'python -m carton catalogue migrate {}' first.".format(
                CATALOGUE_SCHEMA_VERSION, path,
            )
        )
        sys.exit(1)
    raw = (catalogue.get("catalogue_id") or "").strip().lower()
    current = raw if is_valid_registry_id(raw) else ""
    if args.stamp:
        if current:
            print("Already has catalogue_id: {}".format(current))
            return
        new_id = new_registry_id()
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
    ls = sub.add_parser("list", help="List packages in a registry")
    ls.add_argument("registry", help="Path to registry.json")

    # unpublish
    unpub = sub.add_parser("unpublish", help="Force-unpublish a package")
    unpub.add_argument("--registry", required=True, help="Path to registry.json")
    unpub.add_argument("--id", required=True,
                       help="Package id to unpublish ('namespace/name')")
    unpub.add_argument("--force", "-f", action="store_true",
                       help="Skip confirmation prompt")

    # registry subgroup
    reg = sub.add_parser("registry", help="Registry inspection utilities")
    reg_sub = reg.add_subparsers(dest="registry_command")
    rid_p = reg_sub.add_parser(
        "id", help="Print or stamp a registry's registry_id (UUID)",
    )
    rid_p.add_argument("registry", help="Path to registry.json")
    rid_p.add_argument(
        "--stamp", action="store_true",
        help="Write a fresh UUID into the file if it doesn't already have one",
    )

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
    elif args.command == "registry" and getattr(args, "registry_command", None) == "id":
        _registry_id(args)
    elif args.command == "catalogue" and getattr(args, "catalogue_command", None) == "migrate":
        _catalogue_migrate(args)
    elif args.command == "catalogue" and getattr(args, "catalogue_command", None) == "id":
        _catalogue_id(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
