"""Lint a catalogue.json and its referenced artifacts.

Reuses the ``Issue`` / ``LintResult`` primitives from ``carton.core.lint``
so the CLI can format package-lint and catalogue-lint output identically.

Network checks (HEAD requests against ``url``-origin packages, GitHub
Releases probes, etc.) are deliberately opt-in via ``check_network`` —
the default fast path stays usable in CI without flaky external calls.
"""

import json
import os

from carton.core.lint import (
    Issue, LintResult,
    SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO,
    bundled_schema_path,
)


def lint_catalogue(catalogue_path, check_network=False):
    """Lint a catalogue.json and the artifacts it references.

    Returns a ``LintResult`` populated with all findings. ``check_network``
    enables HEAD requests against ``url`` origins; off by default.
    """
    result = LintResult()

    if not os.path.exists(catalogue_path):
        result.add(
            SEVERITY_ERROR, "path_not_found",
            "Catalogue file not found: {}".format(catalogue_path),
        )
        return result

    try:
        with open(catalogue_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        result.add(
            SEVERITY_ERROR, "catalogue_json_syntax",
            "catalogue.json JSON syntax error: {}".format(exc),
            path=catalogue_path,
        )
        return result
    except OSError as exc:
        result.add(
            SEVERITY_ERROR, "catalogue_unreadable",
            "Cannot read catalogue: {}".format(exc),
            path=catalogue_path,
        )
        return result

    # Auto-migrate v4 registries in memory so the rest of the linter only
    # has to think in v5.0 catalogue terms. Surface the migration to the
    # user so they know to write the upgraded file back if they want it
    # persisted on disk.
    schema_version = data.get("schema_version")
    if schema_version != "5.0":
        try:
            from carton.core.migrations import migrate_registry_to_catalogue
            data, _changed = migrate_registry_to_catalogue(data, stamp_id=False)
            result.add(
                SEVERITY_INFO, "schema_migrated_in_memory",
                "schema_version={!r}: linted as v5.0 after in-memory migration. "
                "Run 'carton-maya catalogue migrate <path>' to persist.".format(
                    schema_version,
                ),
            )
        except Exception as exc:  # pragma: no cover
            result.add(
                SEVERITY_ERROR, "migration_failed",
                "Could not migrate to v5.0 in memory: {}".format(exc),
            )
            return result

    _check_schema(data, result)
    _check_catalogue_id(data, result)
    _check_packages(data, os.path.dirname(catalogue_path), result, check_network)

    return result


# ---------------------------------------------------------------------------
# Top-level checks
# ---------------------------------------------------------------------------

def _check_schema(data, result):
    """Validate against the bundled catalogue schema."""
    try:
        import jsonschema
    except ImportError:
        result.add(
            SEVERITY_INFO, "jsonschema_unavailable",
            "jsonschema not installed - skipping schema validation. "
            "Install with: pip install jsonschema",
        )
        return

    schema_path = bundled_schema_path("catalogue.schema.json")
    if not schema_path:
        result.add(
            SEVERITY_ERROR, "schema_missing",
            "Bundled catalogue.schema.json not found in carton-maya install",
        )
        return

    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        result.add(
            SEVERITY_ERROR, "schema_unreadable",
            "Cannot load bundled catalogue schema: {}".format(exc),
        )
        return

    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path_str = "/".join(str(p) for p in err.absolute_path) or "<root>"
        result.add(
            SEVERITY_ERROR, "schema",
            "{}: {}".format(path_str, err.message),
        )


def _check_catalogue_id(data, result):
    """Catalogues without a stamped UUID can't be referenced reliably."""
    cid = (data.get("catalogue_id") or "").strip()
    if not cid:
        result.add(
            SEVERITY_WARNING, "catalogue_id_missing",
            "No catalogue_id stamped. Run "
            "'carton-maya catalogue id <path> --stamp' to add one.",
        )


# ---------------------------------------------------------------------------
# Per-package origin checks
# ---------------------------------------------------------------------------

def _check_packages(data, catalogue_dir, result, check_network):
    """Walk every package entry and validate its origin shape + targets."""
    packages = data.get("packages") or {}

    if not packages:
        result.add(
            SEVERITY_INFO, "empty_catalogue",
            "Catalogue has no packages.",
        )
        return

    for pkg_id, pkg_data in packages.items():
        origin = pkg_data.get("origin") or {}
        otype = origin.get("type")

        if otype is None:
            result.add(
                SEVERITY_ERROR, "origin_type_missing",
                "{}: origin.type missing".format(pkg_id),
            )
            continue

        if otype == "embedded":
            _check_embedded_origin(pkg_id, origin, catalogue_dir, result)
        elif otype == "github":
            _check_github_origin(pkg_id, origin, result, check_network)
        elif otype == "url":
            _check_url_origin(pkg_id, origin, result, check_network)
        elif otype == "local":
            _check_local_origin(pkg_id, origin, result)
        else:
            result.add(
                SEVERITY_ERROR, "origin_type_unknown",
                "{}: unknown origin.type {!r}".format(pkg_id, otype),
            )


def _check_embedded_origin(pkg_id, origin, catalogue_dir, result):
    """Embedded origins host versions inline; verify each zip + sha256."""
    versions = origin.get("versions") or {}
    if not versions:
        result.add(
            SEVERITY_ERROR, "embedded_no_versions",
            "{}: embedded origin has no versions".format(pkg_id),
        )
        return

    for version, ver_data in versions.items():
        url = ver_data.get("download_url")
        if not url:
            result.add(
                SEVERITY_ERROR, "embedded_url_missing",
                "{} v{}: missing download_url".format(pkg_id, version),
            )
            continue

        # Local-relative zip path: verify the file exists on disk.
        if not url.startswith(("http://", "https://")):
            zip_path = os.path.join(catalogue_dir, url)
            if not os.path.exists(zip_path):
                result.add(
                    SEVERITY_ERROR, "embedded_zip_missing",
                    "{} v{}: zip not found at {!r} (relative to catalogue)".format(
                        pkg_id, version, url,
                    ),
                )

        if not ver_data.get("sha256"):
            result.add(
                SEVERITY_WARNING, "embedded_sha256_missing",
                "{} v{}: no sha256 - Strict Verify will refuse this version".format(
                    pkg_id, version,
                ),
            )


def _check_github_origin(pkg_id, origin, result, check_network):
    """github origin needs at least a repo; network probe is opt-in."""
    repo = origin.get("repo")
    if not repo:
        result.add(
            SEVERITY_ERROR, "github_repo_missing",
            "{}: github origin missing 'repo' field".format(pkg_id),
        )
        return
    # Network probe deferred — Releases API requires auth in CI to avoid
    # rate limiting. Surface only as INFO when --check-network flag set.
    if check_network:
        result.add(
            SEVERITY_INFO, "github_check_network_unsupported",
            "{}: --check-network probing for github origins not yet "
            "implemented.".format(pkg_id),
        )


def _check_url_origin(pkg_id, origin, result, check_network):
    """url origin needs a URL string; HEAD request only when --check-network."""
    url = origin.get("url")
    if not url:
        result.add(
            SEVERITY_ERROR, "url_missing",
            "{}: url origin missing 'url' field".format(pkg_id),
        )
        return

    if check_network:
        try:
            from carton.compat_urllib import urlopen, Request
            req = Request(url, method="HEAD")
            try:
                urlopen(req, timeout=5).close()
            except Exception as exc:
                result.add(
                    SEVERITY_WARNING, "url_unreachable",
                    "{}: HEAD {} failed: {}".format(pkg_id, url, exc),
                )
        except ImportError:
            result.add(
                SEVERITY_INFO, "url_check_unavailable",
                "{}: cannot probe URL ({}); urllib unavailable".format(
                    pkg_id, url,
                ),
            )


def _check_local_origin(pkg_id, origin, result):
    """local origin: the path must be present on the linter's machine."""
    path = origin.get("path")
    if not path:
        result.add(
            SEVERITY_ERROR, "local_path_missing",
            "{}: local origin missing 'path' field".format(pkg_id),
        )
        return
    if not os.path.exists(path):
        result.add(
            SEVERITY_WARNING, "local_path_unreachable",
            "{}: local path {!r} not found on this machine".format(pkg_id, path),
        )
