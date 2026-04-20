"""Publisher — write directly to a local registry.

Identity model: each package is keyed by ``"<namespace>/<name>"``. Both must be
set; raise :class:`MissingNamespaceError` if not. The first publish records
``first_published_by`` / ``first_published_at`` on the registry entry; later
publishes by a different author trigger a warning (returned in the result dict)
but are not blocked.
"""

import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone

from carton.compat_urllib import urlopen, Request, URLError
from carton.core import gh_cli as _default_gh_cli
from carton.core.identity import (
    InvalidIdentityError,
    make_pkg_id,
    validate_namespace,
    validate_name,
)
from carton.core.migrations import (
    REGISTRY_SCHEMA_VERSION,
    migrate_registry_data,
)
from carton.core.path_utils import resolve_local_path
from carton.core.registry_id import read_registry_id, stamp_registry_id
from carton.core.sidecar import write_sidecar, read_sidecar


_DEFAULT_MAYA_VERSIONS = ["2024", "2025", "2026", "2027"]


class VersionConflictError(RuntimeError):
    """Raised when attempting to publish a version that already exists."""

    def __init__(self, version):
        self.version = version
        super().__init__(version)


class MissingNamespaceError(RuntimeError):
    """Raised when a publish is attempted without a namespace."""


class RemoteMirrorMissingError(RuntimeError):
    """Raised when a publish targets a remote entry that has no local mirror.

    ``reason`` is one of:
      * ``"no_remote_id"`` — the remote registry itself does not expose a
        ``registry_id`` (so we can't match any local mirror to it).
      * ``"no_local_mirror"`` — the remote has an id but no local entry in
        the current config shares it.
    """

    def __init__(self, remote_entry, reason, remote_id=""):
        self.remote_entry = remote_entry
        self.reason = reason
        self.remote_id = remote_id
        super().__init__(
            "Cannot publish to remote {!r}: {}".format(
                getattr(remote_entry, "name", "<unknown>"), reason,
            )
        )


class InvalidPythonPackageLayoutError(RuntimeError):
    """Raised when a python_package's local_path is the module folder itself.

    Carton expects ``local_path`` to be the *project root* that CONTAINS a
    nested module folder, not the module folder itself. Publishing a module
    folder directly produces a zip whose contents sit at the root, so after
    install ``sys.path`` points at the package dir but ``import <name>``
    cannot find a nested ``<name>/__init__.py`` and fails with
    ModuleNotFoundError.
    """

    def __init__(self, local_path, module_name):
        self.local_path = local_path
        self.module_name = module_name
        super().__init__(
            "Invalid python_package layout: '{path}' contains __init__.py at its "
            "root, so the folder is a Python module itself. Carton expects the "
            "published folder to be a project root that CONTAINS the module as a "
            "nested subfolder.\n\n"
            "Expected layout:\n"
            "  <project>/\n"
            "    package.json\n"
            "    {module}/\n"
            "      __init__.py\n"
            "      ...\n\n"
            "Fix: move package.json up to the parent directory and point "
            "local_path at that parent.".format(path=local_path, module=module_name or "<module_name>")
        )


class Publisher:
    """Publish locally registered scripts to a registry."""

    def __init__(self, config):
        self._config = config

    def publish(self, pkg_data, registry_entry, namespace=None,
                release_notes="", embed_source_path=True):
        include_compiled = bool(pkg_data.get("include_compiled", False))
        """Publish to a registry.

        Args:
            pkg_data: Entry from installed.json. May or may not already carry
                a ``namespace`` field.
            registry_entry: Target RegistryEntry to publish to. Local entries
                are written to directly; remote entries are redirected to
                their same-``registry_id`` local mirror (raises
                :class:`RemoteMirrorMissingError` if no mirror exists).
            namespace: Optional override; if given, takes precedence over
                ``pkg_data['namespace']``. Required if neither is set.

        Returns:
            dict with ``id``, ``namespace``, ``name``, ``version`` and an
            optional ``warnings`` list (e.g. author mismatch). When the user
            selected a remote entry, ``published_via`` carries its name.
        """
        requested_entry = registry_entry
        target_entry = self._resolve_publish_target(registry_entry)

        # Stored local_path may be a portable form like ``~/tools/foo.py``;
        # expand before touching the filesystem.
        local_path = resolve_local_path(pkg_data.get("local_path", ""))
        if not local_path or not os.path.exists(local_path):
            raise RuntimeError("File not found: {}".format(local_path))

        ns_raw = namespace or pkg_data.get("namespace", "")
        if not ns_raw:
            raise MissingNamespaceError(
                "namespace is required to publish; set it in package.json / "
                "sidecar, or pass via the Add dialog."
            )
        try:
            ns = validate_namespace(ns_raw)
            name = validate_name(pkg_data.get("name", ""))
        except InvalidIdentityError as e:
            raise MissingNamespaceError(str(e))

        pkg_id = make_pkg_id(ns, name)

        display_name = pkg_data.get("display_name", name)
        version = pkg_data.get("version", "0.1.0")
        pkg_type = pkg_data.get("type", "python_package")
        icon = pkg_data.get("icon", "")
        description = pkg_data.get("description", "")
        entry_point = pkg_data.get("entry_point", {})
        is_folder = pkg_data.get("is_folder", False)
        author = pkg_data.get("author", "")

        # maya_versions: SoT is package.json. Fall back to inner package.json
        # if the in-memory pkg_data didn't carry the field, and finally to a
        # studio-default tuple.
        maya_versions = self._resolve_maya_versions(pkg_data, local_path, is_folder)

        # Check for same version conflict
        self._check_version_conflict(pkg_id, version, target_entry)

        # Reject the "flat" python_package layout before we waste cycles
        # zipping something that will ModuleNotFoundError at import time.
        self._validate_python_package_layout(local_path, pkg_type, is_folder, name)

        # Build the v5.0 home_origin payload for this embedded publish.
        # pkg_data wins if the caller already carries one (e.g. a tool
        # whose home is elsewhere being published into a mirror), otherwise
        # we stamp the target catalogue's embedded variant. Parallel to
        # the existing home_registry precedence a few lines below.
        home_origin_meta = target_entry.to_home_origin_meta()
        home_origin = pkg_data.get("home_origin") or home_origin_meta

        # 1. Create zip (in staging)
        zip_path = self._create_zip(
            local_path, ns, name, version, is_folder,
            entry_point, display_name, icon, description, pkg_type, author,
            maya_versions=maya_versions,
            home_registry=pkg_data.get("home_registry"),
            home_origin=home_origin,
            include_compiled=include_compiled,
            embed_source_path=embed_source_path,
        )

        sha256 = self._compute_sha256(zip_path)
        size_bytes = os.path.getsize(zip_path)

        # 2. Copy zip to registry directory: packages/<namespace>/<name>/<version>/
        registry_base = target_entry.base_dir
        dest_dir = os.path.join(registry_base, "packages", ns, name, version)
        os.makedirs(dest_dir, exist_ok=True)

        zip_name = "{}-{}.zip".format(name, version)
        dest_zip = os.path.join(dest_dir, zip_name)
        shutil.copy2(zip_path, dest_zip)

        try:
            os.remove(zip_path)
        except OSError:
            pass

        # 3. Copy icon file to registry icons/ directory.
        # Preserve the original filename so consumers can fetch it verbatim.
        registry_icon = icon
        if self._is_icon_file(icon):
            icon_basename = os.path.basename(icon)
            self._copy_icon_to_registry(icon, icon_basename, registry_base)
            registry_icon = icon_basename

        # 4. Update registry.json + rebuild icons.zip
        warnings = self._update_registry(
            registry_entry=target_entry,
            pkg_id=pkg_id,
            namespace=ns,
            name=name,
            display_name=display_name,
            version=version,
            pkg_type=pkg_type,
            description=description,
            icon=registry_icon,
            author=author,
            sha256=sha256,
            size_bytes=size_bytes,
            entry_point=entry_point,
            maya_versions=maya_versions,
            tags=pkg_data.get("tags", []),
            release_notes=release_notes,
        )

        # 5. Persist namespace/name back into source so the next user converges.
        # Use the canonical to_home_meta() builder so the embedded UUID
        # stays consistent with anything else encoded by the UI / config.
        home_meta = target_entry.to_home_meta()
        # Re-build home_origin *after* _update_registry so the stamped
        # registry_id (now on target_entry) propagates into catalogue_id.
        # The earlier ``home_origin`` was handed to the zip when the
        # registry_id may still have been blank — same asymmetry as
        # home_registry, mirrored intentionally.
        home_origin_source = pkg_data.get("home_origin") or target_entry.to_home_origin_meta()
        self._persist_identity_to_source(
            local_path, ns, name, is_folder,
            home_registry=pkg_data.get("home_registry") or home_meta,
            home_origin=home_origin_source,
        )

        result = {"id": pkg_id, "namespace": ns, "name": name, "version": version}
        if requested_entry is not target_entry:
            result["published_via"] = requested_entry.name
        if warnings:
            result["warnings"] = warnings
        return result

    def _resolve_publish_target(self, registry_entry):
        """Return a writable LOCAL RegistryEntry to write into.

        Local entries pass through unchanged. Remote entries are resolved by
        ``registry_id`` to a same-id local mirror from ``self._config``. If
        the remote has no usable id, or no local mirror matches, raise
        :class:`RemoteMirrorMissingError` so the UI layer can guide the user
        through pairing.
        """
        if not registry_entry.is_remote:
            return registry_entry

        remote_id = registry_entry.registry_id
        if not remote_id:
            remote_id = self._probe_remote_registry_id(registry_entry)
            if remote_id:
                # Cache on the live entry so subsequent calls don't re-probe.
                registry_entry.registry_id = remote_id

        if not remote_id:
            raise RemoteMirrorMissingError(registry_entry, reason="no_remote_id")

        mirror = self._config.find_local_mirror(remote_id)
        if mirror is None:
            raise RemoteMirrorMissingError(
                registry_entry, reason="no_local_mirror", remote_id=remote_id,
            )
        return mirror

    @staticmethod
    def _probe_remote_registry_id(registry_entry):
        """One-off HTTP GET to read ``registry_id`` from a remote registry.

        Returns ``""`` on any failure (network, parse, missing field) — the
        caller treats that as ``no_remote_id``.
        """
        try:
            req = Request(registry_entry.path)
            req.add_header("Accept", "application/json")
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, ValueError):
            return ""
        return read_registry_id(data)

    def _validate_python_package_layout(self, local_path, pkg_type, is_folder, name):
        """Reject python_packages where ``local_path`` is the module folder.

        Only applies to folder-based python_package publishes. Single-file
        python scripts and other package types are exempt.
        """
        if pkg_type != "python_package" or not is_folder:
            return
        if not os.path.isdir(local_path):
            return
        if os.path.isfile(os.path.join(local_path, "__init__.py")):
            raise InvalidPythonPackageLayoutError(local_path, name)

    def _resolve_maya_versions(self, pkg_data, local_path, is_folder):
        """Return the maya_versions list to embed in the zip and registry.

        Lookup order: in-memory ``pkg_data`` → existing inner
        ``package.json`` / sidecar → process-wide default. Hardcoded Maya
        versions in publisher code are gone — package.json is the SoT.
        """
        versions = pkg_data.get("maya_versions")
        if versions:
            return list(versions)

        existing = self._read_existing_metadata(local_path, is_folder)
        if existing:
            versions = existing.get("maya_versions")
            if versions:
                return list(versions)

        return list(_DEFAULT_MAYA_VERSIONS)

    @staticmethod
    def _read_existing_metadata(local_path, is_folder):
        """Peek at the existing package.json / sidecar next to the source."""
        try:
            if is_folder:
                pkg_json = os.path.join(local_path, "package.json")
                if os.path.exists(pkg_json):
                    with open(pkg_json, "r", encoding="utf-8") as f:
                        return json.load(f)
            else:
                data = read_sidecar(local_path)
                if data:
                    return data
        except (OSError, ValueError):
            pass
        return None

    def _check_version_conflict(self, pkg_id, version, registry_entry):
        """Check if the same version has already been published."""
        reg_path = os.path.normpath(registry_entry.path)
        if not os.path.exists(reg_path):
            return
        with open(reg_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
        entry = registry.get("packages", {}).get(pkg_id)
        if entry and version in entry.get("versions", {}):
            raise VersionConflictError(version)

    def _create_zip(self, local_path, namespace, name, version, is_folder,
                    entry_point, display_name, icon, description, pkg_type, author,
                    maya_versions=None,
                    home_registry=None, home_origin=None,
                    include_compiled=False,
                    embed_source_path=True):
        """Create a zip file in the staging directory."""
        staging = self._config.staging_dir
        os.makedirs(staging, exist_ok=True)
        zip_path = os.path.join(staging, "{}-{}.zip".format(name, version))

        pkg_json = {
            "schema_version": "4.0",
            "namespace": namespace,
            "name": name,
            "display_name": display_name,
            "version": version,
            "type": pkg_type,
            "description": description,
            "author": author,
            "maya_versions": list(maya_versions) if maya_versions else list(_DEFAULT_MAYA_VERSIONS),
            "entry_point": entry_point,
            "icon": self._normalise_icon_for_storage(icon),
        }
        if embed_source_path:
            # Absolute path of the source files at publish time. The
            # installer uses this to auto-relink My Tools entries when
            # the same user reinstalls Carton on a machine that still
            # has the original sources at this path. Opt-out for public
            # registries where leaking the publisher's directory layout
            # is undesirable.
            pkg_json["source_path"] = os.path.abspath(local_path)
        if home_registry:
            pkg_json["home_registry"] = home_registry
        if home_origin:
            # v5.0: stamp the generalised home pointer alongside the legacy
            # ``home_registry`` so consumers that have already migrated to
            # the ``home_origin`` field don't have to guess the variant
            # (embedded / github / url / local).
            pkg_json["home_origin"] = home_origin

        _EXCLUDE_DIRS = {"__pycache__", ".git", ".svn", ".hg", "tests", "test", "dist", "build", ".vscode", ".idea"}
        _EXCLUDE_FILES = {".gitignore", ".gitattributes", ".DS_Store", "Thumbs.db"}

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if is_folder:
                for root, dirs, files in os.walk(local_path):
                    dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
                    file_set = set(files)
                    for f in files:
                        # Strip .pyc that have a .py sibling — those are
                        # redundant build artifacts. Keep .pyc that ship
                        # standalone (legacy in-house tools without
                        # source). The ``include_compiled`` flag is now
                        # only an override that forces ALL .pyc to be
                        # kept regardless.
                        if f.endswith(".pyc"):
                            sibling_py = f[:-1]  # foo.pyc -> foo.py
                            if sibling_py in file_set and not include_compiled:
                                continue
                        if f in _EXCLUDE_FILES:
                            continue
                        # Skip stale package.json — we'll inject the canonical one
                        if f == "package.json" and root == local_path:
                            continue
                        fp = os.path.join(root, f)
                        arcname = os.path.relpath(fp, local_path)
                        zf.write(fp, arcname)
                zf.writestr("package.json",
                            json.dumps(pkg_json, indent=2, ensure_ascii=False))
            else:
                zf.write(local_path, os.path.basename(local_path))
                zf.writestr("package.json",
                            json.dumps(pkg_json, indent=2, ensure_ascii=False))

        return zip_path

    def _update_registry(self, registry_entry, pkg_id, namespace, name, display_name,
                         version, pkg_type, description, icon, author,
                         sha256, size_bytes, entry_point, maya_versions,
                         tags, release_notes=""):
        """Update registry.json. Returns a list of warning strings (may be empty)."""
        reg_path = os.path.normpath(registry_entry.path)

        if os.path.exists(reg_path):
            with open(reg_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
            # Auto-migrate legacy registries on touch so the schema_version,
            # registry_id, and icon shape are all already at v4.0 by the
            # time we write back.
            registry, _ = migrate_registry_data(registry)
        else:
            registry = {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "registry_id": "",
                "packages": {},
            }

        registry["schema_version"] = REGISTRY_SCHEMA_VERSION
        registry_id, _ = stamp_registry_id(registry)
        registry_entry.registry_id = registry_id

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        warnings = []

        if pkg_id not in registry["packages"]:
            registry["packages"][pkg_id] = {
                "versions": {},
                "first_published_by": author,
                "first_published_at": now,
            }

        entry = registry["packages"][pkg_id]
        # Author mismatch warning (don't block — just inform)
        first_author = entry.get("first_published_by", "")
        if first_author and author and first_author != author:
            warnings.append(
                "author '{}' is publishing a package first published by '{}'".format(
                    author, first_author)
            )
        entry.setdefault("first_published_by", author)
        entry.setdefault("first_published_at", now)

        entry["namespace"] = namespace
        entry["name"] = name
        entry["display_name"] = display_name
        entry["type"] = pkg_type
        entry["description"] = description
        entry["author"] = author
        entry["tags"] = tags
        entry["latest_version"] = version
        # Mirror entry_point as a preview hint so the card UI can show
        # Launch / Activate without installing first. The inner zip's
        # package.json remains the runtime SoT.
        if entry_point:
            entry["entry_point"] = entry_point

        normalised_icon = self._normalise_icon_for_storage(icon)
        if normalised_icon is not None and normalised_icon != "":
            entry["icon"] = normalised_icon
        else:
            entry.pop("icon", None)

        rel_path = "packages/{}/{}/{}/{}-{}.zip".format(namespace, name, version, name, version)
        entry["versions"][version] = {
            "maya_versions": list(maya_versions) if maya_versions else list(_DEFAULT_MAYA_VERSIONS),
            "download_url": rel_path,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "released_at": now,
            "changelog": release_notes or "",
        }

        registry["last_updated"] = now

        os.makedirs(os.path.dirname(reg_path), exist_ok=True)
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)

        self._rebuild_icons_archive(registry_entry.base_dir)
        return warnings

    def _persist_identity_to_source(self, local_path, namespace, name, is_folder,
                                    home_registry=None, home_origin=None):
        """Write namespace/name back into source so other clones converge.

        Folder packages: update or create ``<folder>/package.json``.
        Single files: create or update ``<file>.carton.json`` sidecar.
        """
        updates = {"namespace": namespace, "name": name}
        if home_registry:
            updates["home_registry"] = home_registry
        if home_origin:
            updates["home_origin"] = home_origin

        if is_folder:
            pkg_json_path = os.path.join(local_path, "package.json")
            data = {}
            if os.path.exists(pkg_json_path):
                try:
                    with open(pkg_json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    data = {}
            # Drop legacy id field if present
            data.pop("id", None)
            data.update(updates)
            with open(pkg_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        else:
            existing = read_sidecar(local_path) or {}
            existing.update(updates)
            write_sidecar(local_path, existing)

    def publish_github(self, pkg_data, repo, release_notes="",
                       tag_prefix="v", namespace=None,
                       embed_source_path=False,
                       use_gh_cli=True, gh_cli_module=None):
        """Publish a single package to a GitHub repo as a Release (v5.0).

        This is the github-origin counterpart to :meth:`publish`: instead
        of writing into a local registry/catalogue directory, it builds
        the same zip artifact + a ``SHA256SUMS`` sidecar and uploads them
        as assets on a GitHub Release. A Release with a matching asset
        and a parseable SHA256SUMS is what :class:`GithubOrigin` treats
        as **pinned**, so the resulting origin resolves with is_pinned=True
        and passes strict_verify gates.

        When ``gh`` isn't available (or ``use_gh_cli=False``), the method
        still builds the artifacts and returns copy-pasteable manual
        steps so the user can finish the Release via the web UI.

        Args:
            pkg_data: Entry from installed.json (same shape as
                :meth:`publish` consumes).
            repo: Target ``"owner/name"`` GitHub slug.
            release_notes: Markdown body for the Release.
            tag_prefix: Prepended to version for the git tag
                (``"v"`` + ``"1.2.0"`` → tag ``"v1.2.0"``). Pass ``""``
                to tag with the bare version.
            namespace: Optional override for ``pkg_data['namespace']``.
            embed_source_path: See :meth:`publish`. Defaults to False
                for github publishes since leaking a publisher's local
                directory layout to a public repo's package.json is
                rarely desirable.
            use_gh_cli: When False, skip gh entirely and return manual
                steps — useful for dry-runs and CI preview builds.
            gh_cli_module: Injected module implementing the surface of
                :mod:`carton.core.gh_cli`. Production callers leave this
                None; tests inject a stub.

        Returns:
            Dict with ``id``, ``namespace``, ``name``, ``version``,
            ``repo``, ``tag``, ``zip_path``, ``sha256``, ``sha256sums_path``,
            and either ``release_url`` (when gh succeeded) or
            ``manual_steps`` (when gh unavailable / disabled / failed).
            A ``warnings`` list may be present (e.g. when gh was tried
            but fell back to manual).

        Raises:
            MissingNamespaceError: When namespace/name can't be resolved.
            RuntimeError: When ``local_path`` is missing.
            InvalidPythonPackageLayoutError: For the flat-module trap.
        """
        gh = gh_cli_module or _default_gh_cli

        local_path = resolve_local_path(pkg_data.get("local_path", ""))
        if not local_path or not os.path.exists(local_path):
            raise RuntimeError("File not found: {}".format(local_path))

        ns_raw = namespace or pkg_data.get("namespace", "")
        if not ns_raw:
            raise MissingNamespaceError(
                "namespace is required to publish; set it in package.json / "
                "sidecar, or pass via the Add dialog."
            )
        try:
            ns = validate_namespace(ns_raw)
            name = validate_name(pkg_data.get("name", ""))
        except InvalidIdentityError as e:
            raise MissingNamespaceError(str(e))

        pkg_id = make_pkg_id(ns, name)
        display_name = pkg_data.get("display_name", name)
        version = pkg_data.get("version", "0.1.0")
        pkg_type = pkg_data.get("type", "python_package")
        icon = pkg_data.get("icon", "")
        description = pkg_data.get("description", "")
        entry_point = pkg_data.get("entry_point", {})
        is_folder = pkg_data.get("is_folder", False)
        author = pkg_data.get("author", "")
        include_compiled = bool(pkg_data.get("include_compiled", False))

        maya_versions = self._resolve_maya_versions(pkg_data, local_path, is_folder)
        self._validate_python_package_layout(local_path, pkg_type, is_folder, name)

        # v5.0: stamp home_origin={type:github,repo:<repo>} so the
        # published artifact and the source tree agree on where this
        # package's home is. pkg_data still wins (a publish_github call
        # that explicitly carries a home_origin — e.g. embedded-but-
        # mirrored-to-github — keeps the caller's shape).
        home_origin = pkg_data.get("home_origin") or {
            "type": "github", "repo": repo,
        }

        # Build the same zip shape as the embedded path so consumers
        # installing from either origin see identical package.json bytes.
        zip_path = self._create_zip(
            local_path, ns, name, version, is_folder,
            entry_point, display_name, icon, description, pkg_type, author,
            maya_versions=maya_versions,
            home_registry=pkg_data.get("home_registry"),
            home_origin=home_origin,
            include_compiled=include_compiled,
            embed_source_path=embed_source_path,
        )
        sha256 = self._compute_sha256(zip_path)

        zip_name = os.path.basename(zip_path)
        sums_path = os.path.join(os.path.dirname(zip_path), "SHA256SUMS")
        # Two-space separator + no "*" binary marker: matches the
        # permissive shape GithubOrigin._lookup_sha256_for_asset parses.
        with open(sums_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("{sha}  {name}\n".format(sha=sha256, name=zip_name))

        tag = "{prefix}{version}".format(prefix=tag_prefix, version=version)
        title = "{name} {version}".format(name=display_name or name, version=version)

        result = {
            "id": pkg_id,
            "namespace": ns,
            "name": name,
            "version": version,
            "repo": repo,
            "tag": tag,
            "zip_path": zip_path,
            "sha256": sha256,
            "sha256sums_path": sums_path,
        }
        warnings = []

        gh_usable = bool(use_gh_cli) and gh.is_available()
        if not gh_usable:
            result["manual_steps"] = gh.build_manual_instructions(
                repo, tag, [zip_path, sums_path], notes=release_notes,
            )
            if use_gh_cli:
                # The caller *wanted* automation — surface that we had
                # to fall back so the UI can prompt for ``gh auth login``.
                warnings.append("gh CLI unavailable; fell back to manual steps")
        else:
            try:
                url = gh.create_release(
                    repo, tag,
                    title=title, notes=release_notes,
                    assets=[zip_path, sums_path],
                )
                result["release_url"] = url
            except gh.GhCliError as e:
                # gh was present but the upload failed — keep the
                # artifacts around so the user can retry manually.
                stderr = getattr(e, "stderr", "") or ""
                warnings.append("gh release create failed: {}".format(stderr or str(e)))
                result["manual_steps"] = gh.build_manual_instructions(
                    repo, tag, [zip_path, sums_path], notes=release_notes,
                )

        # Persist identity back into the source tree (same as embedded
        # path) so subsequent publishes from this clone stay consistent.
        self._persist_identity_to_source(
            local_path, ns, name, is_folder,
            home_registry=pkg_data.get("home_registry"),
            home_origin=home_origin,
        )

        if warnings:
            result["warnings"] = warnings
        return result

    def unpublish(self, pkg_id, registry_entry):
        """Remove a package from a registry.

        ``pkg_id`` is the canonical ``"<namespace>/<name>"``. A remote entry
        is redirected to its same-id local mirror; raises
        :class:`RemoteMirrorMissingError` if no mirror exists.
        """
        target_entry = self._resolve_publish_target(registry_entry)
        registry_entry = target_entry

        reg_path = os.path.normpath(registry_entry.path)
        if not os.path.exists(reg_path):
            raise RuntimeError("Registry not found: {}".format(reg_path))

        with open(reg_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
        registry, _ = migrate_registry_data(registry)

        packages = registry.get("packages", {})
        if pkg_id not in packages:
            raise RuntimeError("Package not found in registry: {}".format(pkg_id))

        entry = packages[pkg_id]
        namespace = entry.get("namespace", "")
        name = entry.get("name", pkg_id)

        # Delete the package directory tree
        if namespace and name:
            pkg_dir = os.path.join(registry_entry.base_dir, "packages", namespace, name)
        else:
            pkg_dir = os.path.join(registry_entry.base_dir, "packages", pkg_id)
        if os.path.isdir(pkg_dir):
            shutil.rmtree(pkg_dir)
            # Best-effort cleanup of empty namespace dir
            ns_dir = os.path.dirname(pkg_dir)
            try:
                if not os.listdir(ns_dir):
                    os.rmdir(ns_dir)
            except OSError:
                pass

        del packages[pkg_id]
        registry["last_updated"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)

        return {"id": pkg_id, "name": name}

    def find_published_registries(self, pkg_id):
        """Find all local registries that contain a given package id."""
        results = []
        for entry in self._config.registries:
            if entry.is_remote:
                continue
            reg_path = os.path.normpath(entry.path)
            if not os.path.exists(reg_path):
                continue
            try:
                with open(reg_path, "r", encoding="utf-8") as f:
                    registry = json.load(f)
                if pkg_id in registry.get("packages", {}):
                    results.append(entry)
            except (json.JSONDecodeError, OSError):
                continue
        return results

    @staticmethod
    def _is_icon_file(icon):
        """Return True if icon value is an existing image file path."""
        return (isinstance(icon, str)
                and icon.endswith((".png", ".jpg", ".svg"))
                and os.path.isabs(icon)
                and os.path.exists(icon))

    @staticmethod
    def _normalise_icon_for_storage(icon):
        """Coerce an icon value into the on-disk shape (string | null).

        * Empty string / None → ``None`` (omit field).
        * File path → basename (the publisher copies the file to the
          registry's ``icons/`` directory verbatim).
        * Anything else (emoji, ``"@auto"``, bare filename) → as-is.
        """
        if icon is None or icon == "":
            return None
        if Publisher._is_icon_file(icon):
            return os.path.basename(icon)
        return icon

    @staticmethod
    def _copy_icon_to_registry(icon_path, dest_filename, registry_base):
        """Copy an icon file to the registry's ``icons/`` directory verbatim.

        ``dest_filename`` is the basename to use in the registry; passing the
        original basename keeps the author's filename instead of forcing
        ``<name>.png``.
        """
        icons_dir = os.path.join(registry_base, "icons")
        os.makedirs(icons_dir, exist_ok=True)
        dest = os.path.join(icons_dir, dest_filename)
        shutil.copy2(icon_path, dest)

    def _rebuild_icons_archive(self, registry_base):
        """Rebuild icons.zip from all PNGs in the icons/ directory."""
        icons_dir = os.path.join(registry_base, "icons")
        if not os.path.isdir(icons_dir):
            return
        pngs = [f for f in os.listdir(icons_dir) if f.lower().endswith(".png")]
        if not pngs:
            return
        archive_path = os.path.join(registry_base, "icons.zip")
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for png in pngs:
                zf.write(os.path.join(icons_dir, png), png)

    def _compute_sha256(self, file_path):
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()
