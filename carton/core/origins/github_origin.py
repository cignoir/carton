"""GitHub origin — packages whose artifacts live in a GitHub repo.

Versions are discovered dynamically:

1. ``GET /repos/{owner}/{repo}/releases`` — each Release's tag yields a
   version. Release assets are inspected for a matching artifact
   (``{name}-{version}.zip``) and an optional ``SHA256SUMS`` file.
2. If the repo has no Releases at all, fall back to
   ``GET /repos/{owner}/{repo}/tags`` — each tag becomes a version with
   the GitHub-generated source archive as the artifact (unpinned).

Artifacts are classified as **pinned** when a Release ships a matching
asset AND a parseable ``SHA256SUMS`` entry. Anything else is unpinned;
:class:`carton.core.source_cache.SourceCache` records the first-fetch
sha256 (TOFU) so subsequent installs detect tampering.
"""

from carton.core import github_api
from carton.core.origins.base import (
    ArtifactRef,
    Origin,
    OriginError,
    VersionMeta,
)


_SHA256SUMS_NAMES = ("SHA256SUMS", "SHA256SUMS.txt", "sha256sums", "sha256sums.txt")


class GithubOrigin(Origin):
    """Origin backed by a GitHub repo.

    Args:
        repo: ``owner/repo`` slug, e.g. ``"mystudio/rigger"``.
        ref: Optional pin (tag / branch / commit). When set, the origin
            exposes a single synthetic version named after ``ref`` and
            ignores Releases / Tags enumeration. Useful for early-access
            installs of a feature branch.
        cache: :class:`SourceCache` instance. None disables caching (used
            in tests).
    """

    type = "github"

    def __init__(self, repo, ref="", cache=None):
        if not repo or "/" not in repo:
            raise OriginError("github origin requires 'repo' in 'owner/repo' form")
        self._repo = repo
        self._ref = ref or ""
        self._cache = cache
        # Memoised release / tag responses for the lifetime of this
        # origin object so back-to-back list_versions / get_artifact
        # calls don't re-hit the cache layer.
        self._releases = None
        self._tags = None
        self._default_branch = None

    @classmethod
    def from_dict(cls, data, base_dir=""):
        if data.get("type") != cls.type:
            raise OriginError(
                "expected github origin, got {!r}".format(data.get("type"))
            )
        return cls(repo=data.get("repo", ""), ref=data.get("ref", ""))

    def to_dict(self):
        d = {"type": self.type, "repo": self._repo}
        if self._ref:
            d["ref"] = self._ref
        return d

    def attach_cache(self, cache):
        """Inject a :class:`SourceCache` after construction.

        The catalogue parser can't always know which cache instance to
        wire in, so we expose a setter rather than threading the cache
        through every from_dict signature.
        """
        self._cache = cache

    # ---- version enumeration --------------------------------------------

    def _load_releases(self):
        if self._releases is not None:
            return self._releases
        try:
            self._releases = github_api.list_releases(self._repo, cache=self._cache) or []
        except github_api.GithubApiError:
            self._releases = []
        return self._releases

    def _load_tags(self):
        if self._tags is not None:
            return self._tags
        try:
            self._tags = github_api.list_tags(self._repo, cache=self._cache) or []
        except github_api.GithubApiError:
            self._tags = []
        return self._tags

    def _load_default_branch(self):
        if self._default_branch is not None:
            return self._default_branch
        try:
            self._default_branch = github_api.get_default_branch(
                self._repo, cache=self._cache
            )
        except github_api.GithubApiError:
            self._default_branch = "main"
        return self._default_branch

    def list_versions(self):
        """Return ``{version: VersionMeta}`` for every published version.

        When ``ref`` is set, returns a single synthetic version named
        after the ref. Otherwise enumerates Releases (preferred) and
        falls back to Tags.
        """
        if self._ref:
            return {self._ref: VersionMeta(version=self._ref)}

        out = {}
        for release in self._load_releases():
            tag = release.get("tag_name") or ""
            if not tag or release.get("draft"):
                continue
            ver = github_api.normalise_version_from_tag(tag)
            if ver in out:
                continue
            out[ver] = VersionMeta(
                version=ver,
                released_at=release.get("published_at") or "",
                changelog=release.get("body") or "",
                raw={"tag": tag, "release": release},
            )

        if out:
            return out

        for tag_obj in self._load_tags():
            tag = tag_obj.get("name") or ""
            if not tag:
                continue
            ver = github_api.normalise_version_from_tag(tag)
            if ver in out:
                continue
            out[ver] = VersionMeta(
                version=ver,
                raw={"tag": tag},
            )
        return out

    # ---- artifact resolution --------------------------------------------

    def get_artifact(self, version, package_name=""):
        """Resolve ``version`` to an artifact URL + integrity info.

        ``package_name`` is the bare package name (e.g. ``"rigger"``);
        used to look up a matching Release asset
        (``{package_name}-{version}.zip``). When omitted we accept any
        asset whose filename ends with ``-{version}.zip`` so single-asset
        repos still work without naming gymnastics.
        """
        versions = self.list_versions()
        meta = versions.get(version)
        if meta is None and self._ref and version == self._ref:
            meta = VersionMeta(version=self._ref)
        if meta is None:
            # Last-resort: HEAD of default branch when version matches
            # the magic value "HEAD" — used for unreleased installs.
            if version == "HEAD":
                branch = self._load_default_branch()
                return ArtifactRef(
                    url=github_api.archive_url_for_branch(self._repo, branch),
                    is_pinned=False,
                    source_label="github branch HEAD",
                )
            raise OriginError(
                "github origin {!r} has no version {!r}".format(self._repo, version)
            )

        # Prefer a published Release asset — that's the only way to get
        # a pinned hash without trusting auto-generated archives whose
        # bytes can drift across GitHub's archive backend.
        release = (meta.raw or {}).get("release") if meta else None
        tag = (meta.raw or {}).get("tag") or version

        asset = self._find_artifact_asset(release, package_name, version) if release else None
        if asset:
            sha256 = self._lookup_sha256_for_asset(release, asset.get("name", ""))
            return ArtifactRef(
                url=asset.get("browser_download_url", ""),
                sha256=sha256,
                size_bytes=asset.get("size", 0),
                is_pinned=bool(sha256),
                source_label="github release asset",
            )

        # Fall back to GitHub's auto-generated tag archive. Always
        # unpinned — the SHA may drift if GitHub changes its archive
        # format, so users with strict_verify must use Release assets.
        return ArtifactRef(
            url=github_api.archive_url_for_tag(self._repo, tag),
            is_pinned=False,
            source_label="github auto archive (tag)",
        )

    @staticmethod
    def _find_artifact_asset(release, package_name, version):
        """Return the first Release asset matching ``{name}-{version}.zip``.

        When ``package_name`` is empty, accept any asset ending in
        ``-{version}.zip`` so single-asset repos work without strict
        naming.
        """
        if not isinstance(release, dict):
            return None
        wanted_suffix = "-{}.zip".format(version)
        wanted_exact = "{}-{}.zip".format(package_name, version) if package_name else ""
        for asset in release.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            name = asset.get("name", "")
            if wanted_exact and name == wanted_exact:
                return asset
            if not wanted_exact and name.endswith(wanted_suffix):
                return asset
        return None

    @staticmethod
    def _lookup_sha256_for_asset(release, asset_name):
        """Return the sha256 for ``asset_name`` from a SHA256SUMS sibling.

        Looks for a Release asset with one of the conventional checksum
        filenames, downloads it as text, and parses ``<sha>  <filename>``
        lines. Returns ``""`` when no checksums file is present or the
        asset isn't listed — the caller falls back to unpinned.
        """
        if not isinstance(release, dict) or not asset_name:
            return ""
        sums_url = ""
        for asset in release.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            if asset.get("name", "") in _SHA256SUMS_NAMES:
                sums_url = asset.get("browser_download_url") or ""
                break
        if not sums_url:
            return ""
        body = github_api.fetch_raw_text(sums_url)
        if not body:
            return ""
        for line in body.splitlines():
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            sha, fname = parts[0], parts[-1]
            # SHA256SUMS files often prefix filenames with ``*`` for
            # binary mode — strip it before comparing.
            if fname.lstrip("*") == asset_name and len(sha) == 64:
                return sha.lower()
        return ""
