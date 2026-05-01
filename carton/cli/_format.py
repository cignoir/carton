"""Shared output helpers for CLI subcommands."""


_SEVERITY_PREFIX = {
    "error": "[X]",
    "warning": "[!]",
    "info": "[i]",
}


def format_lint_output(result, path):
    """Pretty-print a LintResult for the human-facing 'lint' command.

    Returns nothing — writes directly to stdout. Single source of truth
    for the lint output format so package-lint and a future
    catalogue-lint print issues the same way.
    """
    print("Linting: {}".format(path))
    print("")

    if not result.issues:
        print("[OK] No issues found.")
        return

    for issue in result.issues:
        prefix = _SEVERITY_PREFIX.get(issue.severity, "[?]")
        print("{} {}: {}".format(prefix, issue.rule, issue.message))
        if issue.path:
            print("    in: {}".format(issue.path))

    print("")
    print("Summary: {} error(s), {} warning(s), {} info(s)".format(
        len(result.errors), len(result.warnings), len(result.infos),
    ))
