"""Fold a ``python_package`` into one shareable ``.py`` file.

This is the CLI-facing sibling of :mod:`carton.core.pack`. ``pack`` builds
the zip you hand to someone who *has* Carton; ``bundle`` builds the single
file you hand to someone who does not — paste it into the Script Editor and
it runs, or drop it in the scripts folder and import it.

The output is the package's own sources concatenated in dependency order,
not an encoded blob, so a file people are meant to open and inspect still
reads like source.

Folding many modules into one namespace is only safe when the package keeps
to a few rules, and a bundle that breaks them is worse than no bundle at all
— it fails at import, or worse, silently resolves a name to the wrong
definition. So this module refuses rather than guesses. It checks that:

* the intra-package import graph has no cycles, so an order exists;
* no two folded modules define the same top-level name, since the fold would
  silently keep only one of them;
* every ``from . import x`` names something the fold can stand in for;
* the result parses and keeps no relative imports.

Only modules reachable from the entry point are folded. A Maya plugin or a
shelf helper that nothing imports stays out on its own, which is usually
what you want — a plugin cannot live inside a Script Editor paste anyway.
"""

import ast
import glob
import io
import json
import os
import re

REL_IMPORT = re.compile(r"^(\s*)from\s+\.{1,2}[\w.]*\s+import\s")


class BundleError(RuntimeError):
    """Raised when ``bundle_package`` cannot produce a single file."""


# ---------------------------------------------------------------------------
#  Reading the package
# ---------------------------------------------------------------------------
def _read(path):
    with io.open(path, encoding="utf-8") as fp:
        return fp.read()


def _load_meta(src_dir):
    pkg_json = os.path.join(src_dir, "package.json")
    if not os.path.exists(pkg_json):
        raise BundleError(
            "package.json not found at {}. "
            "Run `carton-maya package init` to scaffold one.".format(src_dir)
        )
    try:
        meta = json.loads(_read(pkg_json))
    except (OSError, ValueError) as exc:
        raise BundleError("cannot read package.json: {}".format(exc))
    if meta.get("type") != "python_package":
        raise BundleError(
            "only python_package can be bundled into a single file "
            "(this one is {!r})".format(meta.get("type"))
        )
    entry = meta.get("entry_point") or {}
    module = entry.get("module")
    if not module:
        raise BundleError("package.json has no entry_point.module")
    if not os.path.isdir(os.path.join(src_dir, module)):
        raise BundleError(
            "entry_point.module {!r} is not a folder in {}".format(module, src_dir)
        )
    return meta, module, entry.get("function") or "show"


def _collect_modules(src_dir, pkg):
    """Map ``dotted.module.name`` -> (relative path, source)."""
    out = {}
    base = os.path.join(src_dir, pkg)
    for dirpath, dirnames, files in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            dotted = rel[:-3].replace("/", ".")
            if dotted.endswith(".__init__"):
                dotted = dotted[: -len(".__init__")]
            out[dotted] = (rel, _read(full))
    if pkg not in out:
        raise BundleError("{}/__init__.py not found".format(pkg))
    return out


# ---------------------------------------------------------------------------
#  Understanding it
# ---------------------------------------------------------------------------
def _package_of(dotted, mods):
    """The package a module's relative imports are resolved against."""
    return dotted if dotted in mods and _is_package(dotted, mods) else \
        dotted.rsplit(".", 1)[0] if "." in dotted else dotted


def _is_package(dotted, mods):
    prefix = dotted + "."
    return any(m.startswith(prefix) for m in mods)


def _resolve(dotted, level, module, mods):
    """Turn a relative import inside ``dotted`` into an absolute name."""
    parts = _package_of(dotted, mods).split(".")
    for _ in range(level - 1):
        parts = parts[:-1]
        if not parts:
            break
    if module:
        parts = parts + module.split(".")
    return ".".join(parts)


class _ModuleInfo(object):
    """What the bundler needs to know about one module."""

    def __init__(self, dotted, rel, src, mods, pkg):
        self.dotted = dotted
        self.rel = rel
        self.src = src
        self.pkg = pkg
        self.deps = set()          # modules that must come first
        self.reach = set()         # modules this one can pull in at all
        self.aliases = {}          # local name -> module it stands for
        self.names = set()         # top-level definitions
        self.maya_imports = []     # (statement, bound name)
        self.drop_lines = set()    # 1-based lines the fold must not keep
        self.drop_starts = {}      # first line of each -> its indent column
        self.shim = False          # nothing but imports and __all__
        self.file_at_import = 0    # line where __file__ is read at import time
        self._scan(mods)

    def _own(self, name):
        return name == self.pkg or name.startswith(self.pkg + ".")

    def _mark(self, node):
        # Remember where the statement starts as well as which lines it spans.
        # An import wrapped over several lines is still one statement, so it
        # may only leave one ``pass`` behind, at its own indent — not one per
        # continuation line.
        self.drop_starts[node.lineno] = node.col_offset
        for line in range(node.lineno, getattr(node, "end_lineno",
                                               node.lineno) + 1):
            self.drop_lines.add(line)

    def _note(self, target, mods, top):
        """Record a module this one uses, and whether order depends on it."""
        if target not in mods:
            return
        self.reach.add(target)
        if top:
            # Only an import that runs at import time constrains the order
            # modules can be written in. One inside a function runs later, by
            # which point every name in the file already exists — which is how
            # a package that imports itself lazily can still be folded.
            self.deps.add(target)

    def _visit(self, body, mods, top):
        for node in body:
            if isinstance(node, ast.ImportFrom):
                # Both spellings reach the same modules, and these packages use
                # both: relative inside the tree, absolute from the entry point.
                if node.level:
                    target = _resolve(self.dotted, node.level, node.module, mods)
                elif node.module == "__future__":
                    self._mark(node)
                    continue
                elif node.module and self._own(node.module):
                    target = node.module
                else:
                    continue
                self._mark(node)
                if node.module:
                    self._note(target, mods, top)
                for alias in node.names:
                    sub = target + "." + alias.name
                    if sub in mods:
                        self._note(sub, mods, top)
                        self.aliases[alias.asname or alias.name] = sub
                    elif not node.module:
                        self._note(target, mods, top)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".")[0]
                    if head == "maya" and top:
                        # Only a module-level `import maya...` has to move into
                        # the guarded prologue, so the file still loads outside
                        # Maya. One inside a function is usually the author
                        # asking "am I running in Maya?" and has to keep
                        # raising, or the answer becomes a lie.
                        self._mark(node)
                        bound = alias.asname or head
                        stmt = "import {}{}".format(
                            alias.name,
                            " as " + alias.asname if alias.asname else "")
                        if (stmt, bound) not in self.maya_imports:
                            self.maya_imports.append((stmt, bound))
                    elif self._own(alias.name):
                        self._mark(node)
                        self._note(alias.name, mods, top)
                        if alias.name in mods:
                            self.aliases[alias.asname or head] = alias.name
            else:
                nested = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                           ast.ClassDef))
                if top and not nested and not self.file_at_import:
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Name) and inner.id == "__file__":
                            self.file_at_import = inner.lineno
                            break
                for field in ("body", "orelse", "finalbody", "handlers"):
                    for child in getattr(node, field, None) or []:
                        if isinstance(child, ast.AST) and hasattr(child, "body"):
                            self._visit(child.body, mods, top and not nested)
                            self._visit(getattr(child, "orelse", []) or [],
                                        mods, top and not nested)
                        elif isinstance(child, ast.AST):
                            self._visit([child], mods, top and not nested)

    def _scan(self, mods):
        try:
            tree = ast.parse(self.src, self.rel)
        except SyntaxError as exc:
            raise BundleError("{}: {}".format(self.rel, exc))

        self._visit(tree.body, mods, top=True)

        body = list(tree.body)
        if body and isinstance(body[0], ast.Expr) and \
                isinstance(body[0].value, ast.Constant) and \
                isinstance(body[0].value.value, str):
            body = body[1:]          # drop the module docstring
        self.shim = bool(body) and all(
            isinstance(n, (ast.Import, ast.ImportFrom))
            or (isinstance(n, ast.Assign)
                and all(getattr(t, "id", "") == "__all__" for t in n.targets))
            for n in body
        )

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                self.names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.names.add(t.id)


def _reachable(entry, infos):
    """Modules the entry point can actually pull in, transitively."""
    seen, stack = set(), [entry]
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in infos:
            continue
        seen.add(cur)
        stack.extend(infos[cur].reach)
    return seen


def _order(names, infos):
    """Dependency order, or raise on a cycle."""
    order, done, active = [], set(), []

    def visit(mod, trail):
        if mod in done:
            return
        if mod in trail:
            cycle = trail[trail.index(mod):] + [mod]
            raise BundleError(
                "circular imports cannot be folded into one file: {}".format(
                    " -> ".join(cycle))
            )
        trail.append(mod)
        for dep in sorted(infos[mod].deps):
            if dep in names:
                visit(dep, trail)
        trail.pop()
        done.add(mod)
        order.append(mod)

    for mod in sorted(names):
        visit(mod, active)
    return order


# ---------------------------------------------------------------------------
#  Rewriting it
# ---------------------------------------------------------------------------
def _strip(info):
    """Drop the import statements a single file must not keep.

    Which lines go comes from the parse, not from matching text, so an
    ``import`` written inside a docstring as a usage example survives intact.
    An import that lived inside a function leaves a ``pass`` behind, so the
    block it was the only statement of does not end up empty.
    """
    out = []
    for number, line in enumerate(info.src.split("\n"), 1):
        if number not in info.drop_lines:
            out.append(line)
            continue
        column = info.drop_starts.get(number)
        if column:
            out.append(" " * column + "pass")
    return "\n".join(out).strip("\n")


HEADER = '''# -*- coding: utf-8 -*-
"""{title} {version} — single-file build.

{description}

Load it from a file — that is the reliable way::

    # put this file in your Maya scripts folder, e.g.
    #   ~/Documents/maya/scripts/{out_module}.py
    import {out_module} as tool
    tool.{function}()

Somewhere else on disk? Paste just these two lines. They are pure ASCII, so
the Script Editor cannot mangle them, and they read this file as UTF-8::

    path = r"C:/somewhere/{out_module}.py"
    exec(compile(open(path, encoding="utf-8").read(), path, "exec"))

Pasting the whole file into the Script Editor works too and opens the window
straight away, but on a Windows install whose locale is not UTF-8 the paste
can arrive with its non-ASCII text corrupted. Prefer one of the two above.

------------------------------------------------------------------------
Generated from the {pkg} package by `carton-maya package bundle`.
Do not edit this file — fix the package and build it again.
------------------------------------------------------------------------
"""

from __future__ import annotations

{stdlib}

{maya}

class _SelfModule(object):
    """Stands in for a module the package referred to by name.

    The package says things like ``theme.COLOR`` or ``scene.load()``. Folded
    into one file every one of those names is just a global here, so each
    module reference becomes one of these and resolves straight back into
    this file. That keeps every call site exactly as the package wrote it.
    """

    __slots__ = ("_name",)

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return "<single-file module {{}}>".format(self._name)

    def __getattr__(self, name):
        try:
            return globals()[name]
        except KeyError:
            raise AttributeError("{{}}.{{}}".format(self._name, name))


{aliases}
{data}
'''

DATA_INTRO = '''
# ---------------------------------------------------------------------------
#  Data files the package reads at runtime, carried along inside this build.
#
#  A package that folds into one file has no folder next to it any more, so
#  anything it used to read off disk travels here instead. The package looks
#  this name up and falls back to reading the disk when it is absent — which
#  is what happens when it runs as a normal package.
#
#  Text is escaped to plain ASCII on purpose: it survives a copy-paste through
#  a console or editor that is not on a UTF-8 locale.
# ---------------------------------------------------------------------------
BUNDLED_DATA = {
'''

STDLIB_GUESS = ("bisect", "math", "os", "sys", "json", "re", "itertools",
                "collections", "functools", "copy", "time", "random")


def _data_files(src_dir, meta, pkg):
    """Runtime data the package asked to have carried along.

    ``package.json`` names them under ``bundle.data`` as globs relative to the
    package folder. Nothing is guessed: a file only travels because the author
    said it has to.
    """
    patterns = ((meta.get("bundle") or {}).get("data")) or []
    if isinstance(patterns, str):
        patterns = [patterns]
    found = {}
    base = os.path.join(src_dir, pkg)
    for pattern in patterns:
        matches = sorted(glob.glob(os.path.join(base, pattern.replace("/", os.sep))))
        if not matches:
            raise BundleError(
                "bundle.data pattern {!r} matched nothing under {}".format(
                    pattern, base)
            )
        for path in matches:
            if os.path.isfile(path):
                rel = os.path.relpath(path, base).replace(os.sep, "/")
                found[rel] = _read(path)
    return found


def _data_block(files):
    if not files:
        return ""
    lines = [DATA_INTRO.rstrip("\n")]
    for rel in sorted(files):
        lines.append("    {}: {},".format(json.dumps(rel),
                                          json.dumps(files[rel])))
    lines.append("}")
    return "\n".join(lines) + "\n"


def _prologue(meta, pkg, function, out_module, infos, order, data_files=None):
    maya_stmts, aliases = [], {}
    stdlib = set()
    for mod in order:
        info = infos[mod]
        for stmt, bound in info.maya_imports:
            if (stmt, bound) not in maya_stmts:
                maya_stmts.append((stmt, bound))
        for local, target in info.aliases.items():
            aliases[local] = target
        for node in ast.walk(ast.parse(info.src, info.rel)):
            if isinstance(node, ast.Import) and node.lineno not in info.drop_lines:
                for a in node.names:
                    top = a.name.split(".")[0]
                    if top in STDLIB_GUESS:
                        stdlib.add(top)

    maya_block = ""
    if maya_stmts:
        lines = ["try:"]
        lines += ["    " + stmt for stmt, _ in maya_stmts]
        lines.append("except ImportError:"
                     "                 # importable outside Maya too")
        lines += ["    {} = None".format(bound) for _, bound in maya_stmts]
        maya_block = "\n".join(lines) + "\n"

    alias_block = "\n".join(
        '{} = _SelfModule("{}")'.format(local, local)
        for local in sorted(aliases)
    )

    desc = meta.get("description")
    if isinstance(desc, dict):
        desc = desc.get("en") or next(iter(desc.values()), "")
    return HEADER.format(
        title=meta.get("display_name") or pkg,
        version=meta.get("version", "0.0.0"),
        description=(desc or "").strip(),
        out_module=out_module,
        function=function,
        pkg=pkg,
        stdlib="\n".join("import {}".format(m) for m in sorted(stdlib)),
        maya=maya_block,
        aliases=alias_block,
        data=_data_block(data_files or {}),
    ), set(aliases)


# ---------------------------------------------------------------------------
#  Checking it
# ---------------------------------------------------------------------------
def _find_file_reads(order, infos):
    """Modules that read ``__file__`` while being imported.

    A single file has no folder beside it, and pasted into the Script Editor
    it has no ``__file__`` at all, so this fails the moment the bundle loads.
    Reading it inside a function is the package's own business — it can guard
    for the name being missing, and often should.
    """
    return [
        "{} reads __file__ at import time (line {}) — a single file has no "
        "folder beside it, and a pasted one has no __file__ at all".format(
            infos[mod].rel, infos[mod].file_at_import)
        for mod in order if infos[mod].file_at_import
    ]


def _find_collisions(order, infos, alias_names):
    problems, owner = [], {}
    for mod in order:
        for name in sorted(infos[mod].names):
            if name.startswith("__") and name.endswith("__"):
                continue
            owner.setdefault(name, []).append(mod)
    for name, mods in sorted(owner.items()):
        if len(mods) > 1:
            problems.append(
                "{!r} is defined by {} — folding them into one namespace "
                "would keep only the last".format(name, " and ".join(mods))
            )
        if name in alias_names:
            problems.append(
                "{!r} is both a module the package refers to and a name "
                "defined in {}".format(name, mods[0])
            )
    return problems


def verify(src, pkg=None, aliases=()):
    """Everything wrong with the file that was just built.

    The checks before this one read the package; these read the result, which
    is what catches a mistake in the folding itself. Both go through the parse
    rather than the text, because a usage example inside a docstring reads
    exactly like the import it describes.
    """
    problems = []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return ["the generated file does not parse: {} (line {})".format(
            exc.msg, exc.lineno)]

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            problems.append(
                "line {}: a package-relative import survived".format(node.lineno))
        elif isinstance(node, ast.ImportFrom) and pkg \
                and (node.module or "").split(".")[0] == pkg:
            problems.append(
                "line {}: an import of the package survived".format(node.lineno))
        elif isinstance(node, ast.Import) and pkg:
            for alias in node.names:
                if alias.name.split(".")[0] == pkg:
                    problems.append(
                        "line {}: an import of the package survived".format(
                            node.lineno))

    seen = {}
    skip = set(aliases) | {"BUNDLED_DATA"}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        else:
            names = []
        for name in names:
            if name.startswith("__") or name in skip:
                continue
            if name in seen:
                problems.append(
                    "{!r} is defined twice in the result, at lines {} and {}"
                    .format(name, seen[name], node.lineno))
            seen[name] = node.lineno
    return problems


# ---------------------------------------------------------------------------
#  Public entry points
# ---------------------------------------------------------------------------
def plan_bundle(src_dir):
    """Work out what a bundle would contain, and what stops it.

    Returns ``(order, infos, problems, meta, pkg, function)`` without writing
    anything, so linting and building can share one answer.
    """
    src_dir = os.path.abspath(src_dir)
    if not os.path.isdir(src_dir):
        raise BundleError("not a directory: {}".format(src_dir))
    meta, pkg, function = _load_meta(src_dir)
    mods = _collect_modules(src_dir, pkg)

    infos = {}
    for dotted, (rel, src) in sorted(mods.items()):
        infos[dotted] = _ModuleInfo(dotted, rel, src, mods, pkg)

    live = _reachable(pkg, infos)
    # Pure re-export shims carry nothing of their own; splice their edges out
    # so the modules behind them still come first.
    for mod in sorted(live):
        if not infos[mod].shim:
            continue
        for other in live:
            for bucket in ("deps", "reach"):
                edges = getattr(infos[other], bucket)
                if mod in edges:
                    edges.discard(mod)
                    edges |= getattr(infos[mod], bucket)
    keep = sorted(m for m in live if not infos[m].shim)
    for mod in keep:
        infos[mod].deps &= set(keep)

    order = _order(keep, infos)
    # The entry point reads as the public face of the tool, so it goes last
    # unless something actually has to be written after it.
    if pkg in order and not any(pkg in infos[m].deps for m in keep if m != pkg):
        order = [m for m in order if m != pkg] + [pkg]
    alias_names = set()
    for mod in order:
        alias_names |= set(infos[mod].aliases)
    problems = _find_collisions(order, infos, alias_names)
    problems += _find_file_reads(order, infos)
    return order, infos, problems, meta, pkg, function


def build_source(src_dir, out_module=None):
    """Return the single-file source for the package at ``src_dir``."""
    order, infos, problems, meta, pkg, function = plan_bundle(src_dir)
    if problems:
        raise BundleError(
            "this package cannot be folded into one file:\n"
            + "\n".join("  " + p for p in problems)
        )
    out_module = out_module or (pkg + "_standalone")
    prologue, aliases = _prologue(meta, pkg, function, out_module, infos, order,
                                  _data_files(os.path.abspath(src_dir), meta, pkg))

    parts = [prologue]
    for mod in order:
        parts.append("\n\n# {0}\n# {1}\n# {0}\n\n{2}\n".format(
            "=" * 74, infos[mod].rel, _strip(infos[mod])))
    parts.append(
        "\n\n# {0}\n#  Pasted into the Script Editor? Open the window.\n"
        "# {0}\nif __name__ == \"__main__\":\n    {1}()\n".format(
            "-" * 74, function))
    src = "".join(parts)

    late = verify(src, pkg, aliases)
    if late:
        raise BundleError(
            "the generated file did not come out usable:\n"
            + "\n".join("  " + p for p in late)
        )
    return src


def bundle_package(src_dir, out_path=None, check=False):
    """Write ``<pkg>_standalone.py`` next to the package (or at ``out_path``).

    With ``check`` the file is only compared against what would be generated,
    which is how a repository keeps a committed bundle from going stale.
    Returns the path written or checked.
    """
    src_dir = os.path.abspath(src_dir)
    _meta, pkg, _fn = _load_meta(src_dir)
    dest = os.path.abspath(out_path or os.path.join(src_dir,
                                                    pkg + "_standalone.py"))
    out_module = os.path.basename(dest)[:-3]
    src = build_source(src_dir, out_module=out_module)

    if check:
        if not os.path.exists(dest):
            raise BundleError("{} has not been built yet".format(dest))
        if _read(dest) != src:
            raise BundleError(
                "{} is out of date — build it again".format(dest))
        return dest

    parent = os.path.dirname(dest)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with io.open(dest, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(src)
    return dest
