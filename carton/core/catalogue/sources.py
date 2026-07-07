"""Catalogue-source acquisition: probes, resolution, and registration.

Everything here is Qt-free and side-effect-explicit so the Settings UI
(and any future CLI command) can drive "add a catalogue / register a
single package" flows without owning network or filesystem logic.
Historically this lived inside the ``RegistriesSection`` widget, which
made the transports untestable and welded HTTP calls to a QWidget.

Network calls are synchronous with short timeouts; callers on the UI
thread decide whether to wrap them in a worker.
"""

import json
import os

from urllib.request import Request, urlopen
from urllib.error import URLError

from carton.core.uuid_id import read_uuid


class CatalogueSourceError(Exception):
    """A source could not be resolved / registered; message is user-facing."""


# Outcomes of the single-package registration flows.
RESULT_REGISTERED = "registered"
RESULT_ALREADY_ADDED = "already_added"
RESULT_NOT_A_PACKAGE = "not_a_package"


# ---- probes (moved from carton.ui._catalogue_pairing) ---------------------


def read_local_catalogue_id(path):
    """Peek at a local catalogue.json and return its (id, data) tuple.

    Returns ``(id, data_dict)`` where ``id`` may be empty. Returns
    ``("", None)`` on read / parse failure — callers should surface the
    error to the user in their own context. Accepts the legacy v4.0
    ``registry_id`` key as a fallback so stamping still works on an
    un-migrated file.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return "", None
    cid = read_uuid(data, "catalogue_id") or read_uuid(data, "registry_id")
    return cid, data


def probe_remote_catalogue_meta(url, timeout=15):
    """One-off HTTP GET to a URL; return ``{catalogue_id, display_name}``.

    Any network / parse error yields an all-empty dict. Callers pick the
    field they need and ignore the rest. Centralised so a single round
    trip populates both the UUID cache and the display_name cache on
    first registration — we want subscribers to adopt the author's
    intended name immediately rather than prompting for an alias.
    """
    result = {"catalogue_id": "", "display_name": ""}
    try:
        req = Request(url)
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, ValueError):
        return result
    cid = read_uuid(data, "catalogue_id") or read_uuid(data, "registry_id")
    if cid:
        result["catalogue_id"] = cid
    name = (data.get("display_name") or "").strip()
    if name:
        result["display_name"] = name
    return result


def probe_remote_catalogue_id(url, timeout=15):
    """Return just the ``catalogue_id`` from the remote catalogue.

    Thin wrapper around :func:`probe_remote_catalogue_meta` — kept as a
    named alias so older call sites that only care about the UUID read
    cleanly. New code that also wants the display_name should call
    ``probe_remote_catalogue_meta`` directly to avoid a second round trip.
    """
    return probe_remote_catalogue_meta(url, timeout=timeout)["catalogue_id"]


def probe_github_package_json(base_url, timeout=10):
    """One-off HTTP GET to ``{base_url}/package.json``; return the parsed dict.

    Used by the Settings > Add GitHub flow to decide whether the target
    repo is a v5.0 single-package repo before falling back to the multi-
    package ``catalogue.json`` probe. Any network / parse failure yields
    ``None`` — the caller interprets that as "no package.json here".
    """
    url = base_url.rstrip("/") + "/package.json"
    try:
        req = Request(url)
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "getcode", lambda: 200)() != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_duplicate_entry(catalogues, cid, new_path, ignore=None):
    """Return the first catalogue that collides with ``(cid, new_path)``, or None.

    * Entries with a different ``catalogue_id`` (or none) never collide.
    * The entry located at the same normalised path as ``new_path`` is not a
      collision — it's the user re-selecting a catalogue that's already in
      the list verbatim.
    * Any entry in ``ignore`` is skipped. Used by the pairing flow to pass
      the remote that *should* share the UUID with the new local mirror —
      that's the whole point of pairing, so flagging it would be wrong.
    """
    if not cid:
        return None
    ignore_set = set(id(e) for e in (ignore or []) if e is not None)
    normalized = normalize_catalogue_path(new_path) if new_path else ""
    for entry in catalogues:
        if id(entry) in ignore_set:
            continue
        if normalized and entry.path == normalized:
            continue
        entry_cid = getattr(entry, "catalogue_id", "")
        if entry_cid and entry_cid == cid:
            return entry
    return None


def normalize_catalogue_path(path):
    """Mirror ``CatalogueEntry``'s path normalisation for comparisons."""
    if path.startswith(("http://", "https://")):
        return path
    return os.path.normpath(path)


# ---- GitHub resolution -----------------------------------------------------


def resolve_github_base(repo, timeout=10):
    """Resolve ``owner/name`` to its raw-content base URL.

    Asks the GitHub API for the default branch so ``main`` vs ``master``
    repos both work. Raises :class:`CatalogueSourceError` when the repo
    is unreachable (bad name, rate limit, offline).
    """
    try:
        api_url = "https://api.github.com/repos/{}".format(repo)
        req = Request(api_url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        branch = data.get("default_branch", "main")
    except Exception as e:
        raise CatalogueSourceError(str(e))
    return "https://raw.githubusercontent.com/{}/{}".format(repo, branch)


def probe_github_catalogue_url(base, timeout=10):
    """Return the first catalogue/registry URL that exists under ``base``.

    Probe order: v5.0 catalogue before v4.0 registry, nested layout
    before root (preserves the habit of the sample repos — the official
    template publishes under ``registry/catalogue.json``). Returns None
    when nothing answers.
    """
    candidates = [
        base + "/registry/catalogue.json",
        base + "/catalogue.json",
        base + "/registry/registry.json",
        base + "/registry.json",
    ]
    for url in candidates:
        try:
            req = Request(url)
            with urlopen(req, timeout=timeout) as resp:
                if resp.getcode() == 200:
                    return url
        except Exception:
            continue
    return None


# ---- single-package registration (personal catalogue) ----------------------


def register_github_single_package(base, repo, timeout=10):
    """Register ``{base}/package.json`` as a github-origin personal package.

    Returns ``(result, pkg_id)`` where result is one of the ``RESULT_*``
    constants. ``RESULT_NOT_A_PACKAGE`` means no (usable) package.json —
    the caller falls through to the catalogue probe. Raises
    :class:`CatalogueSourceError` if the personal catalogue can't be
    written.
    """
    pkg_data = probe_github_package_json(base, timeout=timeout)
    if pkg_data is None:
        return RESULT_NOT_A_PACKAGE, ""
    return _register_personal(
        pkg_data, lambda catalogue, pkg_id:
        catalogue.add_github_package(pkg_id, repo))


def register_url_single_package(url, timeout=10):
    """Register a direct ``package.json`` URL as a url-origin personal package.

    Counterpart to :func:`register_github_single_package` for repos that
    aren't on GitHub (or host their manifest at a non-standard path).
    Raises :class:`CatalogueSourceError` when the URL can't be fetched or
    parsed, or the personal catalogue can't be written.
    """
    try:
        req = Request(url)
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=timeout) as resp:
            pkg_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise CatalogueSourceError(str(e))
    if not isinstance(pkg_data, dict):
        return RESULT_NOT_A_PACKAGE, ""
    return _register_personal(
        pkg_data, lambda catalogue, pkg_id:
        catalogue.add_url_package(pkg_id, url))


def _register_personal(pkg_data, add):
    from carton.core.catalogue.personal import PersonalCatalogue, derive_pkg_id

    pkg_id = derive_pkg_id(pkg_data)
    if not pkg_id:
        # Manifest exists but lacks namespace/name — the caller decides
        # whether to fall through to a catalogue probe or warn.
        return RESULT_NOT_A_PACKAGE, ""
    catalogue = PersonalCatalogue.load()
    if catalogue.contains(pkg_id):
        return RESULT_ALREADY_ADDED, pkg_id
    add(catalogue, pkg_id)
    try:
        catalogue.save()
    except OSError as e:
        raise CatalogueSourceError(str(e))
    return RESULT_REGISTERED, pkg_id


# ---- local catalogue scaffolding -------------------------------------------


def scaffold_local_catalogue(folder):
    """Ensure ``folder`` hosts a catalogue; return (path, display_name, id).

    Pre-existing ``catalogue.json`` / ``registry.json`` are left alone —
    the caller just registers the path and :class:`CatalogueClient`
    reads / auto-migrates them on first fetch (their id is returned
    empty; the client caches the real one later). Only the "folder has
    neither" case creates a new file, and it's always v5.0.

    Raises OSError (or json errors) on write failure.
    """
    from carton.core.catalogue.io import write_catalogue_dict
    from carton.core.migrations import (
        CATALOGUE_FILENAME,
        CATALOGUE_SCHEMA_VERSION,
        LEGACY_REGISTRY_FILENAME,
    )
    from carton.core.uuid_id import new_uuid

    cat_path = os.path.join(folder, CATALOGUE_FILENAME)
    legacy_path = os.path.join(folder, LEGACY_REGISTRY_FILENAME)
    display_name = os.path.basename(os.path.normpath(folder))

    if os.path.exists(cat_path):
        return cat_path, display_name, ""
    if os.path.exists(legacy_path):
        return legacy_path, display_name, ""

    catalogue_id = new_uuid()
    os.makedirs(folder, exist_ok=True)
    write_catalogue_dict(cat_path, {
        "schema_version": CATALOGUE_SCHEMA_VERSION,
        "catalogue_id": catalogue_id,
        "display_name": display_name,
        "packages": {},
    })
    os.makedirs(os.path.join(folder, "packages"), exist_ok=True)
    return cat_path, display_name, catalogue_id
