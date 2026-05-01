"""``carton-maya package <command>`` — author-facing per-package operations."""

import os
import sys

from carton.cli._format import format_lint_output


def register_package_subparser(sub):
    """Wire the ``package`` group onto the top-level parser."""
    pkg = sub.add_parser(
        "package", help="Per-package operations (author-facing)",
    )
    pkg_sub = pkg.add_subparsers(dest="package_command")

    lint_p = pkg_sub.add_parser(
        "lint",
        help="Validate a package's metadata and structure (warnings + errors)",
    )
    lint_p.add_argument(
        "path", nargs="?", default=".",
        help="Path to package folder or single file (default: .)",
    )

    check_p = pkg_sub.add_parser(
        "check",
        help="Lint in CI mode (errors only, exit code only)",
    )
    check_p.add_argument(
        "path", nargs="?", default=".",
        help="Path to package folder or single file (default: .)",
    )

    pkg_sub.add_parser(
        "schema",
        help="Print the package.json JSON Schema (for IDE completion)",
    )


def dispatch_package(args, parser):
    """Route a parsed ``package <subcmd>`` invocation to its handler."""
    cmd = getattr(args, "package_command", None)
    if cmd == "lint":
        _package_lint(args)
    elif cmd == "check":
        _package_check(args)
    elif cmd == "schema":
        _package_schema(args)
    else:
        parser.parse_args(["package", "--help"])


def _package_lint(args):
    from carton.core.lint import lint_package

    target = os.path.abspath(args.path or ".")
    result = lint_package(target)
    format_lint_output(result, target)
    if result.has_errors():
        sys.exit(1)


def _package_check(args):
    from carton.core.lint import lint_package

    target = os.path.abspath(args.path or ".")
    result = lint_package(target)
    if result.has_errors():
        for issue in result.errors:
            print("ERROR {}: {}".format(issue.rule, issue.message), file=sys.stderr)
        sys.exit(1)


def _package_schema(args):
    """Print the package.json JSON Schema to stdout."""
    _print_bundled_schema("package.schema.json")


def _print_bundled_schema(filename):
    from carton.core.lint import bundled_schema_path

    path = bundled_schema_path(filename)
    if not path:
        print(
            "ERROR: bundled {} not found in carton-maya install".format(filename),
            file=sys.stderr,
        )
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        sys.stdout.write(f.read())
