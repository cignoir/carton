"""Lint a Carton package directory or single-file script.

The CLI's ``carton-maya package lint`` and ``package check`` commands both
funnel through ``lint_package`` here. The result is a ``LintResult`` that
groups issues by severity so the human-facing ``lint`` formatter can pretty-
print them and the CI-facing ``check`` can just inspect the exit code.

Rule design notes:
  * Every check returns ``Issue`` objects, never raises — the goal is to
    surface ALL problems on a single run, not bail on the first.
  * Severities follow the ``error`` / ``warning`` / ``info`` convention:
    errors fail ``check``, warnings inform but don't fail, infos are
    diagnostic context (auto-detected type, etc.).
  * Schema validation happens through jsonschema. The schema file ships
    inside the carton-maya wheel under ``carton/data/schemas/``.
"""

import json
import os

from carton.core.detect import scan_folder
from carton.core.maya_module_detect import find_module_files, parse_mod_file


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


class Issue(object):
    """A single lint finding."""

    __slots__ = ("severity", "rule", "message", "path")

    def __init__(self, severity, rule, message, path=None):
        self.severity = severity
        self.rule = rule
        self.message = message
        self.path = path

    def __repr__(self):
        return "Issue({!r}, {!r}, {!r})".format(
            self.severity, self.rule, self.message,
        )


class LintResult(object):
    """Container for issues found by ``lint_package``."""

    def __init__(self):
        self.issues = []

    def add(self, severity, rule, message, path=None):
        self.issues.append(Issue(severity, rule, message, path))

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == SEVERITY_ERROR]

    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == SEVERITY_WARNING]

    @property
    def infos(self):
        return [i for i in self.issues if i.severity == SEVERITY_INFO]

    def has_errors(self):
        return bool(self.errors)


def lint_package(path):
    """Lint a package directory or single-file script.

    Returns a ``LintResult``. Always returns even when ``path`` is broken;
    the result will contain an error issue describing the problem.
    """
    result = LintResult()

    if not os.path.exists(path):
        result.add(
            SEVERITY_ERROR, "path_not_found",
            "Path does not exist: {}".format(path),
        )
        return result

    if os.path.isfile(path):
        _lint_single_file(path, result)
    else:
        _lint_folder(path, result)

    return result


# ---------------------------------------------------------------------------
# Single-file lint
# ---------------------------------------------------------------------------

def _lint_single_file(path, result):
    """Lint a single .py / .mel / .mll script + its sidecar."""
    ext = os.path.splitext(path)[1].lower()

    if ext not in (".py", ".mel", ".mll"):
        result.add(
            SEVERITY_WARNING, "unknown_extension",
            "Unknown file extension {!r} - Carton supports .py / .mel / .mll".format(ext),
            path=path,
        )
        return

    sidecar_path = path + ".carton.json"
    if not os.path.exists(sidecar_path):
        result.add(
            SEVERITY_WARNING, "sidecar_missing",
            "No sidecar file found at {}. Carton creates one on first publish; "
            "commit it alongside the script for shareability.".format(
                os.path.basename(sidecar_path)),
        )
        return

    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        result.add(
            SEVERITY_ERROR, "sidecar_syntax",
            "Sidecar JSON syntax error: {}".format(exc),
            path=sidecar_path,
        )
        return
    except OSError as exc:
        result.add(
            SEVERITY_ERROR, "sidecar_unreadable",
            "Cannot read sidecar: {}".format(exc),
            path=sidecar_path,
        )
        return

    _check_metadata(data, os.path.dirname(path), result)


# ---------------------------------------------------------------------------
# Folder lint
# ---------------------------------------------------------------------------

def _lint_folder(folder, result):
    """Lint a package folder (with or without package.json)."""
    info = scan_folder(folder)

    vendor_seen = info.get("vendor_dirs_seen") or []
    if vendor_seen and not info.get("has_package_json") and not info.get("is_maya_module"):
        result.add(
            SEVERITY_WARNING, "vendor_dirs",
            "Vendor-style directories found at root: {}. "
            "Auto-type detection skips them, but ensure they're in .gitignore "
            "and not part of the published artifact.".format(", ".join(vendor_seen)),
        )

    pkg_json_path = os.path.join(folder, "package.json")

    if not os.path.exists(pkg_json_path):
        # Maya module: package.json optional, .mod / PackageContents.xml drives
        if info.get("is_maya_module"):
            _check_mod_files(folder, result)
            result.add(
                SEVERITY_INFO, "auto_detected_type",
                "Detected as maya_module (no package.json required for this type).",
            )
            return

        result.add(
            SEVERITY_WARNING, "package_json_missing",
            "No package.json at folder root. Carton will rely on auto-detection at "
            "registration time, which can misclassify packages with vendored "
            "Python files. Adding a package.json eliminates this risk.",
        )
        result.add(
            SEVERITY_INFO, "auto_detected_type",
            "Auto-detected: type={}, name={}".format(info.get("type"), info.get("name")),
        )
        return

    # package.json present
    try:
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        result.add(
            SEVERITY_ERROR, "package_json_syntax",
            "package.json JSON syntax error: {}".format(exc),
            path=pkg_json_path,
        )
        return
    except OSError as exc:
        result.add(
            SEVERITY_ERROR, "package_json_unreadable",
            "Cannot read package.json: {}".format(exc),
            path=pkg_json_path,
        )
        return

    _check_metadata(data, folder, result)

    if data.get("type") == "maya_module":
        _check_mod_files(folder, result)


# ---------------------------------------------------------------------------
# Metadata-level checks (shared between folder package.json and sidecar)
# ---------------------------------------------------------------------------

def _check_metadata(data, root_dir, result):
    """Run all metadata checks against a parsed package.json or sidecar dict."""
    _check_schema(data, result)
    _check_plugin_platform(data, result)
    _check_entry_point_files(data, root_dir, result)
    _check_icon_path(data, root_dir, result)


def _check_schema(data, result):
    """Validate metadata against the bundled JSON Schema."""
    try:
        import jsonschema
    except ImportError:
        result.add(
            SEVERITY_INFO, "jsonschema_unavailable",
            "jsonschema not installed - skipping schema validation. "
            "Install with: pip install jsonschema",
        )
        _check_required_fields_minimal(data, result)
        return

    schema_path = bundled_schema_path("package.schema.json")
    if not schema_path:
        result.add(
            SEVERITY_ERROR, "schema_missing",
            "Bundled package.schema.json not found in carton-maya install",
        )
        return

    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        result.add(
            SEVERITY_ERROR, "schema_unreadable",
            "Cannot load bundled schema: {}".format(exc),
        )
        return

    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path_str = "/".join(str(p) for p in err.absolute_path) or "<root>"
        result.add(
            SEVERITY_ERROR, "schema",
            "{}: {}".format(path_str, err.message),
        )


def _check_required_fields_minimal(data, result):
    """Fallback when jsonschema isn't available - check the absolute essentials."""
    required = ["name", "display_name", "version", "type", "entry_point"]
    for field in required:
        if field not in data:
            result.add(
                SEVERITY_ERROR, "required_field",
                "Missing required field: {}".format(field),
            )


def _check_plugin_platform(data, result):
    """type=plugin requires a platform field."""
    if data.get("type") == "plugin" and not data.get("platform"):
        result.add(
            SEVERITY_ERROR, "plugin_platform_required",
            "type=plugin requires 'platform' field, e.g. [\"win64\"]",
        )


def _check_entry_point_files(data, root_dir, result):
    """Verify files referenced in entry_point actually exist on disk."""
    ep = data.get("entry_point") or {}
    if not isinstance(ep, dict):
        return  # legacy "module:function" string form, skip

    ep_type = ep.get("type")

    if ep_type == "python":
        module = ep.get("module") or ""
        if module:
            init_path = os.path.join(root_dir, module, "__init__.py")
            module_py = os.path.join(root_dir, module + ".py")
            if not (os.path.exists(init_path) or os.path.exists(module_py)):
                result.add(
                    SEVERITY_ERROR, "entry_point_module_missing",
                    "entry_point.module {!r} not found - expected "
                    "{}/__init__.py or {}.py at the package root".format(
                        module, module, module),
                )
    elif ep_type == "exec":
        f = ep.get("file") or ""
        if f and not os.path.exists(os.path.join(root_dir, f)):
            result.add(
                SEVERITY_ERROR, "entry_point_file_missing",
                "entry_point.file {!r} not found in package".format(f),
            )
    elif ep_type == "mel":
        script = ep.get("script") or ""
        if script:
            # Look in scripts/ first (folder convention), then root
            candidates = [
                os.path.join(root_dir, "scripts", script),
                os.path.join(root_dir, script),
            ]
            if not any(os.path.exists(p) for p in candidates):
                result.add(
                    SEVERITY_ERROR, "entry_point_script_missing",
                    "entry_point.script {!r} not found in scripts/ or root".format(
                        script),
                )
    elif ep_type == "plugin":
        plugin_file = ep.get("plugin_file") or ""
        if plugin_file:
            # Look for plugin_file.mll under plug-ins/
            mll = plugin_file + ".mll"
            found = False
            plugins_dir = os.path.join(root_dir, "plug-ins")
            if os.path.isdir(plugins_dir):
                for root, dirs, files in os.walk(plugins_dir):
                    if mll in files:
                        found = True
                        break
            if not found:
                result.add(
                    SEVERITY_ERROR, "entry_point_plugin_missing",
                    "entry_point.plugin_file {!r} - no {} found under plug-ins/".format(
                        plugin_file, mll),
                )


def _check_icon_path(data, root_dir, result):
    """If icon points at a relative file path, check it exists."""
    icon = data.get("icon")
    if not isinstance(icon, str) or not icon:
        return
    if icon == "@auto":
        return
    if not icon.endswith((".png", ".jpg", ".svg")):
        # Likely an emoji
        return
    if os.path.isabs(icon):
        return
    full = os.path.join(root_dir, icon)
    if not os.path.exists(full):
        result.add(
            SEVERITY_ERROR, "icon_missing",
            "icon path {!r} not found in package".format(icon),
        )


def _check_mod_files(folder, result):
    """Validate .mod / PackageContents.xml syntax for maya_module folders."""
    pkg_contents, mod_files = find_module_files(folder)

    if not (pkg_contents or mod_files):
        result.add(
            SEVERITY_ERROR, "module_marker_missing",
            "type=maya_module but no .mod or PackageContents.xml found at folder root",
        )
        return

    for mod_path in mod_files:
        parsed = parse_mod_file(mod_path)
        if not parsed:
            result.add(
                SEVERITY_WARNING, "mod_unparseable",
                "Could not parse {} - check '+ MAYAVERSION:... NAME VERSION PATH' "
                "format".format(os.path.basename(mod_path)),
                path=mod_path,
            )
            continue

        # Read raw lines to check for MAYAVERSION on every + block
        try:
            with open(mod_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue

        for lineno, raw in enumerate(lines, start=1):
            line = raw.strip()
            if line.startswith("+") and "MAYAVERSION:" not in line:
                result.add(
                    SEVERITY_WARNING, "mod_no_mayaversion",
                    "{}:{}: '+' block has no MAYAVERSION: - this module will "
                    "load on every Maya version, which is risky for binary "
                    ".mll dispatch".format(os.path.basename(mod_path), lineno),
                    path=mod_path,
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def bundled_schema_path(filename):
    """Return absolute path to a schema bundled inside the carton-maya wheel.

    Returns ``None`` if the file isn't shipped (which would be a
    packaging bug, since ``carton/data/schemas/`` is included via
    ``pyproject.toml`` package-data).
    """
    # carton/data/schemas/<filename>
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(here, "data", "schemas", filename)
    if os.path.exists(candidate):
        return candidate
    return None
