"""Publisher — write directly to a local v5.0 catalogue.

Identity model: each package is keyed by ``"<namespace>/<name>"``. Both must be
set; raise :class:`MissingNamespaceError` if not. The first publish records
``first_published_by`` / ``first_published_at`` on the catalogue entry; later
publishes by a different author trigger a warning (returned in the result dict)
but are not blocked.
"""

import json
import os
import shutil
from datetime import datetime, timezone

from carton.compat_urllib import urlopen, Request, URLError
from carton.core import gh_cli as _default_gh_cli
from carton.core._publisher_catalogue import update_catalogue
from carton.core._publisher_zip import create_zip
from carton.core.catalogue_icons import (
    copy_icon_to_catalogue,
    is_icon_file,
)
from carton.core.hash_verify import compute_sha256
from carton.core.identity import (
    InvalidIdentityError,
    make_pkg_id,
    validate_namespace,
    validate_name,
)
from carton.core.migrations import (
    CATALOGUE_FILENAME,
    LEGACY_REGISTRY_FILENAME,
    migrate_local_registry_file_to_catalogue,
    migrate_registry_to_catalogue,
)
from carton.core.path_utils import resolve_local_path
from carton.core.uuid_id import read_uuid
from carton.core.sidecar import read_sidecar


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
      * ``"no_remote_id"`` — the remote catalogue itself does not expose a
        ``catalogue_id`` (so we can't match any local mirror to it).
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
    """Publish locally registered scripts into a v5.0 catalogue."""

    def __init__(self, config):
        self._config = config

    def publish(self, pkg_data, catalogue_entry, namespace=None,
                release_notes="", embed_source_path=True):
        include_compiled = bool(pkg_data.get("include_compiled", False))
        """Publish to a local catalogue.

        Args:
            pkg_data: Entry from installed.json. May or may not already carry
                a ``namespace`` field.
            catalogue_entry: Target CatalogueEntry to publish to. Local
                entries are written to directly; remote entries are
                redirected to their same-``catalogue_id`` local mirror
                (raises :class:`RemoteMirrorMissingError` if no mirror
                exists).
            namespace: Optional override; if given, takes precedence over
                ``pkg_data['namespace']``. Required if neither is set.

        Returns:
            dict with ``id``, ``namespace``, ``name``, ``version`` and an
            optional ``warnings`` list (e.g. author mismatch). When the user
            selected a remote entry, ``published_via`` carries its name.
        """
        requested_entry = catalogue_entry
        target_entry = self._resolve_publish_target(catalogue_entry)

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

        # Resolve the writable catalogue.json path up front. If the entry
        # still points at a legacy registry.json the file-level migrator
        # renames the old file to ``registry.json.bak-v0.4.<ms>`` and
        # creates catalogue.json alongside so subsequent writes land on
        # the v5.0 file.
        catalogue_path = self._resolve_catalogue_write_path(target_entry.path)

        # Check for same version conflict before we waste cycles building
        # the artifact.
        self._check_version_conflict(pkg_id, version, catalogue_path)

        # Reject the "flat" python_package layout before we waste cycles
        # zipping something that will ModuleNotFoundError at import time.
        self._validate_python_package_layout(local_path, pkg_type, is_folder, name)

        # Build the v5.0 home_origin payload for this embedded publish.
        # pkg_data wins if the caller already carries one (e.g. a tool
        # whose home is elsewhere being published into a mirror), otherwise
        # we stamp the target catalogue's embedded variant.
        home_origin_meta = target_entry.to_home_origin_meta()
        home_origin = pkg_data.get("home_origin") or home_origin_meta

        # 1. Create zip (in staging)
        zip_path = create_zip(
            self._config.staging_dir,
            local_path, ns, name, version, is_folder,
            entry_point, display_name, icon, description, pkg_type, author,
            maya_versions=maya_versions,
            home_origin=home_origin,
            include_compiled=include_compiled,
            embed_source_path=embed_source_path,
        )

        sha256 = compute_sha256(zip_path)
        size_bytes = os.path.getsize(zip_path)

        # 2. Copy zip to catalogue directory: packages/<namespace>/<name>/<version>/
        catalogue_base = target_entry.base_dir
        dest_dir = os.path.join(catalogue_base, "packages", ns, name, version)
        os.makedirs(dest_dir, exist_ok=True)

        zip_name = "{}-{}.zip".format(name, version)
        dest_zip = os.path.join(dest_dir, zip_name)
        shutil.copy2(zip_path, dest_zip)

        try:
            os.remove(zip_path)
        except OSError:
            pass

        # 3. Copy icon file to catalogue icons/ directory.
        # Preserve the original filename so consumers can fetch it verbatim.
        stored_icon = icon
        if is_icon_file(icon):
            icon_basename = os.path.basename(icon)
            copy_icon_to_catalogue(icon, icon_basename, catalogue_base)
            stored_icon = icon_basename

        # 4. Update catalogue.json + rebuild icons.zip
        warnings = update_catalogue(
            catalogue_path=catalogue_path,
            catalogue_entry=target_entry,
            pkg_id=pkg_id,
            namespace=ns,
            name=name,
            display_name=display_name,
            version=version,
            pkg_type=pkg_type,
            description=description,
            icon=stored_icon,
            author=author,
            sha256=sha256,
            size_bytes=size_bytes,
            entry_point=entry_point,
            maya_versions=maya_versions,
            tags=pkg_data.get("tags", []),
            release_notes=release_notes,
        )

        # The author's source is sacred — namespace/name/home_origin are
        # persisted into the zip and the catalogue, never back-written to
        # the source package.json. Subscribers who want identity on their
        # machine read from installed.json (populated by the installer).

        result = {"id": pkg_id, "namespace": ns, "name": name, "version": version}
        if requested_entry is not target_entry:
            result["published_via"] = requested_entry.label
        if warnings:
            result["warnings"] = warnings
        return result

    def _resolve_publish_target(self, catalogue_entry):
        """Return a writable LOCAL CatalogueEntry to write into.

        Local entries pass through unchanged. Remote entries are resolved by
        ``catalogue_id`` to a same-id local mirror from ``self._config``. If
        the remote has no usable id, or no local mirror matches, raise
        :class:`RemoteMirrorMissingError` so the UI layer can guide the user
        through pairing.
        """
        if not catalogue_entry.is_remote:
            return catalogue_entry

        remote_id = catalogue_entry.catalogue_id
        if not remote_id:
            remote_id = self._probe_remote_catalogue_id(catalogue_entry)
            if remote_id:
                # Cache on the live entry so subsequent calls don't re-probe.
                catalogue_entry.catalogue_id = remote_id

        if not remote_id:
            raise RemoteMirrorMissingError(catalogue_entry, reason="no_remote_id")

        mirror = self._config.find_local_mirror(remote_id)
        if mirror is None:
            raise RemoteMirrorMissingError(
                catalogue_entry, reason="no_local_mirror", remote_id=remote_id,
            )
        return mirror

    @staticmethod
    def _probe_remote_catalogue_id(catalogue_entry):
        """One-off HTTP GET to read ``catalogue_id`` from a remote catalogue.

        Returns ``""`` on any failure (network, parse, missing field) — the
        caller treats that as ``no_remote_id``. Accepts the legacy
        ``registry_id`` key as a fallback for catalogues that haven't been
        migrated on the producer side yet.
        """
        try:
            req = Request(catalogue_entry.path)
            req.add_header("Accept", "application/json")
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, ValueError):
            return ""
        cid = read_uuid(data, "catalogue_id")
        if cid:
            return cid
        return read_uuid(data, "registry_id")

    @staticmethod
    def _resolve_catalogue_write_path(entry_path):
        """Return the on-disk path that ``publish`` should read from / write to.

        Accepts paths pointing at ``registry.json``, ``catalogue.json``, or
        an unrelated filename. If the entry still points at a legacy
        ``registry.json``, the file-level migrator is invoked to rename
        it to ``.bak-v0.4.<ms>`` and create ``catalogue.json`` in the
        same directory — subsequent publishes then write directly to the
        new file without needing another migration pass.
        """
        if not entry_path:
            return entry_path
        path = os.path.normpath(entry_path)
        base = os.path.basename(path).lower()
        parent = os.path.dirname(path)
        if base == LEGACY_REGISTRY_FILENAME:
            catalogue_path = os.path.join(parent, CATALOGUE_FILENAME)
            if os.path.exists(catalogue_path):
                return catalogue_path
            if os.path.exists(path):
                new_path = migrate_local_registry_file_to_catalogue(path)
                if new_path:
                    return new_path
            # Fresh init — caller will create catalogue.json.
            return catalogue_path
        return path

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
        """Return the maya_versions list to embed in the zip and catalogue.

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

    @staticmethod
    def _check_version_conflict(pkg_id, version, catalogue_path):
        """Raise :class:`VersionConflictError` if ``version`` already exists.

        Reads the catalogue.json at ``catalogue_path`` (if any) and
        checks ``packages[pkg_id]["origin"]["versions"]``. Accepts v4.0
        registries transparently by running them through the in-memory
        migrator first.
        """
        if not os.path.exists(catalogue_path):
            return
        with open(catalogue_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data, _ = migrate_registry_to_catalogue(data, stamp_id=False)
        entry = (data.get("packages") or {}).get(pkg_id)
        if not entry:
            return
        origin = entry.get("origin") or {}
        if version in (origin.get("versions") or {}):
            raise VersionConflictError(version)

    def publish_github(self, pkg_data, repo, release_notes="",
                       tag_prefix="v", namespace=None,
                       embed_source_path=False,
                       use_gh_cli=True, gh_cli_module=None):
        """Publish a single package to a GitHub repo as a Release (v5.0).

        This is the github-origin counterpart to :meth:`publish`: instead
        of writing into a local catalogue directory, it builds the same
        zip artifact + a ``SHA256SUMS`` sidecar and uploads them as
        assets on a GitHub Release. A Release with a matching asset and
        a parseable SHA256SUMS is what :class:`GithubOrigin` treats as
        **pinned**, so the resulting origin resolves with is_pinned=True
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

        # Stamp home_origin={type:github,repo:<repo>} so the published
        # artifact and the source tree agree on where this package's
        # home is. pkg_data still wins (a publish_github call that
        # explicitly carries a home_origin — e.g. embedded-but-mirrored-
        # to-github — keeps the caller's shape).
        home_origin = pkg_data.get("home_origin") or {
            "type": "github", "repo": repo,
        }

        # Build the same zip shape as the embedded path so consumers
        # installing from either origin see identical package.json bytes.
        zip_path = create_zip(
            self._config.staging_dir,
            local_path, ns, name, version, is_folder,
            entry_point, display_name, icon, description, pkg_type, author,
            maya_versions=maya_versions,
            home_origin=home_origin,
            include_compiled=include_compiled,
            embed_source_path=embed_source_path,
        )
        sha256 = compute_sha256(zip_path)

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

        if warnings:
            result["warnings"] = warnings
        return result

    def unpublish(self, pkg_id, catalogue_entry):
        """Remove a package from a catalogue.

        ``pkg_id`` is the canonical ``"<namespace>/<name>"``. A remote entry
        is redirected to its same-id local mirror; raises
        :class:`RemoteMirrorMissingError` if no mirror exists.
        """
        target_entry = self._resolve_publish_target(catalogue_entry)
        catalogue_path = self._resolve_catalogue_write_path(target_entry.path)

        if not os.path.exists(catalogue_path):
            raise RuntimeError("Catalogue not found: {}".format(catalogue_path))

        with open(catalogue_path, "r", encoding="utf-8") as f:
            catalogue = json.load(f)
        catalogue, _ = migrate_registry_to_catalogue(catalogue)

        packages = catalogue.get("packages", {})
        if pkg_id not in packages:
            raise RuntimeError("Package not found in catalogue: {}".format(pkg_id))

        entry = packages[pkg_id]
        namespace = entry.get("namespace", "")
        name = entry.get("name", pkg_id)

        # Delete the package directory tree
        if namespace and name:
            pkg_dir = os.path.join(target_entry.base_dir, "packages", namespace, name)
        else:
            pkg_dir = os.path.join(target_entry.base_dir, "packages", pkg_id)
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
        catalogue["last_updated"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        with open(catalogue_path, "w", encoding="utf-8") as f:
            json.dump(catalogue, f, indent=2, ensure_ascii=False)

        return {"id": pkg_id, "name": name}

    def find_published_catalogues(self, pkg_id):
        """Find all local catalogues that contain a given package id."""
        results = []
        for entry in self._config.catalogues:
            if entry.is_remote:
                continue
            catalogue_path = self._resolve_catalogue_write_path(entry.path)
            if not catalogue_path or not os.path.exists(catalogue_path):
                continue
            try:
                with open(catalogue_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data, _ = migrate_registry_to_catalogue(data, stamp_id=False)
                if pkg_id in (data.get("packages") or {}):
                    results.append(entry)
            except (json.JSONDecodeError, OSError):
                continue
        return results
