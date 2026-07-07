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

    init_p = pkg_sub.add_parser(
        "init",
        help="Scaffold a new Carton package from a bundled template",
    )
    init_p.add_argument(
        "path", nargs="?", default=".",
        help="Target folder for the scaffold (default: .)",
    )
    init_p.add_argument(
        "--type", dest="pkg_type",
        choices=("python_package", "mel_script", "plugin", "maya_module"),
        help="Package type (skip the prompt)",
    )
    init_p.add_argument("--name", help="Package name (snake_case)")
    init_p.add_argument(
        "--namespace", default=None,
        help="Publisher namespace (e.g. mystudio). Required to publish; "
             "omit to scaffold without one",
    )
    init_p.add_argument("--display-name", dest="display_name")
    init_p.add_argument("--version", default=None, help="Initial version (default: 0.1.0)")
    init_p.add_argument("--description", default=None)
    init_p.add_argument("--author", default=None)
    init_p.add_argument(
        "--maya-versions", dest="maya_versions",
        help="Comma-separated Maya versions (default: 2024,2025,2026)",
    )
    init_p.add_argument(
        "--platform", default=None,
        help="Comma-separated platforms for type=plugin (default: win64)",
    )
    init_p.add_argument(
        "--non-interactive", action="store_true",
        help="Skip prompts; fill missing fields with defaults",
    )
    init_p.add_argument(
        "--force", action="store_true",
        help="Overwrite even if the target folder already has files",
    )

    pack_p = pkg_sub.add_parser(
        "pack",
        help="Build a publishable <name>-<version>.zip from a package folder",
    )
    pack_p.add_argument(
        "path", nargs="?", default=".",
        help="Path to package folder (default: .)",
    )
    pack_p.add_argument(
        "--out", default="dist",
        help="Output directory for the zip (default: ./dist)",
    )
    pack_p.add_argument(
        "--no-validate", action="store_true",
        help="Skip lint check before packing (not recommended)",
    )
    pack_p.add_argument(
        "--include-compiled", action="store_true",
        help="Include .pyc files even when a sibling .py exists",
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
    elif cmd == "pack":
        _package_pack(args)
    elif cmd == "init":
        _package_init(args)
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


def _package_init(args):
    from carton.core.init_template import (
        InitError, build_context, render_template,
        DEFAULT_MAYA_VERSIONS, PACKAGE_TYPES,
    )

    target = os.path.abspath(args.path or ".")
    default_name = _slugify(os.path.basename(target.rstrip(os.sep)) or "my_tool")

    if args.non_interactive:
        answers = _init_defaults_only(args, default_name)
    else:
        answers = _init_prompt(args, default_name)

    if answers["pkg_type"] not in PACKAGE_TYPES:
        print(
            "ERROR: invalid type {!r} (expected {})".format(
                answers["pkg_type"], ", ".join(PACKAGE_TYPES)
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    ctx = build_context(
        name=answers["name"],
        display_name=answers["display_name"],
        version=answers["version"],
        description=answers["description"],
        author=answers["author"],
        maya_versions=answers["maya_versions"] or list(DEFAULT_MAYA_VERSIONS),
        platform=answers.get("platform"),
        namespace=answers.get("namespace", ""),
    )

    try:
        written = render_template(
            answers["pkg_type"], target, ctx, force=args.force,
        )
    except InitError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        sys.exit(1)

    print("Scaffolded {} ({}) at {}".format(
        answers["name"], answers["pkg_type"], target,
    ))
    for path in written:
        print("  {}".format(os.path.relpath(path, target)))
    print("\nNext: edit package.json and run `carton-maya package lint`.")


def _init_defaults_only(args, default_name):
    """Build the answer dict from CLI flags + sensible defaults (no prompts)."""
    name = args.name or default_name
    return {
        "pkg_type": args.pkg_type or "python_package",
        "name": name,
        "namespace": _clean_namespace(args.namespace or ""),
        "display_name": args.display_name or _to_display_name(name),
        "version": args.version or "0.1.0",
        "description": args.description or "",
        "author": args.author or "",
        "maya_versions": _parse_csv(args.maya_versions),
        "platform": _parse_csv(args.platform),
    }


def _clean_namespace(raw):
    """Slugify + validate a namespace; exit with an error if unusable.

    Empty input is fine (the field is omitted from package.json and the
    author adds it later / via the GUI), but a namespace that survives
    neither slugify nor validation would scaffold an unpublishable
    package — fail loudly instead.
    """
    from carton.core.identity import (
        InvalidIdentityError, slugify_namespace, validate_namespace,
    )
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return validate_namespace(slugify_namespace(raw))
    except InvalidIdentityError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        sys.exit(1)


def _init_prompt(args, default_name):
    """Drive an interactive scaffold via questionary, falling back to flags."""
    try:
        import questionary
    except ImportError:
        print(
            "questionary is not installed — falling back to defaults. "
            "Install carton-maya[dev] or pass --non-interactive to silence this.",
            file=sys.stderr,
        )
        return _init_defaults_only(args, default_name)

    pkg_type = args.pkg_type or questionary.select(
        "Package type?",
        choices=["python_package", "mel_script", "plugin", "maya_module"],
        default="python_package",
    ).ask()
    if pkg_type is None:  # user hit Ctrl-C
        sys.exit(130)

    name = args.name or questionary.text(
        "Package name (snake_case)?", default=default_name,
    ).ask()
    if not name:
        sys.exit(130)

    namespace = args.namespace
    if namespace is None:
        namespace = questionary.text(
            "Namespace (publisher id, e.g. mystudio — required to publish, "
            "empty to skip)?",
            default="",
        ).ask()
        if namespace is None:
            sys.exit(130)
    namespace = _clean_namespace(namespace)

    display_name = args.display_name or questionary.text(
        "Display name?", default=_to_display_name(name),
    ).ask()
    version = args.version or questionary.text(
        "Initial version?", default="0.1.0",
    ).ask()
    description = args.description or questionary.text(
        "One-line description?", default="",
    ).ask() or ""
    author = args.author or questionary.text(
        "Author?", default="",
    ).ask() or ""

    maya_versions = _parse_csv(args.maya_versions)
    if not maya_versions:
        picked = questionary.checkbox(
            "Maya versions?",
            choices=[
                questionary.Choice("2024", checked=True),
                questionary.Choice("2025", checked=True),
                questionary.Choice("2026", checked=True),
                questionary.Choice("2027"),
            ],
        ).ask()
        maya_versions = picked or list(["2024", "2025", "2026"])

    platform = _parse_csv(args.platform)
    if pkg_type == "plugin" and not platform:
        picked = questionary.checkbox(
            "Plugin platforms?",
            choices=[
                questionary.Choice("win64", checked=True),
                questionary.Choice("linux"),
                questionary.Choice("mac"),
            ],
        ).ask()
        platform = picked or ["win64"]

    return {
        "pkg_type": pkg_type,
        "name": name,
        "namespace": namespace,
        "display_name": display_name,
        "version": version,
        "description": description,
        "author": author,
        "maya_versions": maya_versions,
        "platform": platform,
    }


def _parse_csv(raw):
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _slugify(s):
    """Lowercase + replace non-[a-z0-9_-] with '_'. Keeps name lint-clean."""
    out = []
    for ch in s.lower():
        if ch.isalnum() or ch in "_-":
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out).strip("_-")
    return slug or "my_tool"


def _to_display_name(name):
    """``my_tool`` → ``My Tool`` for the prompt default."""
    return " ".join(part.capitalize() for part in name.replace("-", "_").split("_") if part)


def _package_pack(args):
    from carton.core.pack import pack_package, PackError

    target = os.path.abspath(args.path or ".")
    out_dir = os.path.abspath(args.out)
    try:
        zip_path = pack_package(
            target,
            out_dir=out_dir,
            validate=not args.no_validate,
            include_compiled=args.include_compiled,
        )
    except PackError as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        sys.exit(1)
    print("Built {}".format(zip_path))


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
