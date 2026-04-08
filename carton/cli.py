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

    args = parser.parse_args()

    if args.command == "list":
        _list_packages(args)
    elif args.command == "unpublish":
        _unpublish(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
