"""Thin wrapper around GitHub's REST API.

Used by :class:`carton.core.origins.github_origin.GithubOrigin` to enumerate
versions and locate artifact URLs. Reads come through
:class:`carton.core.source_cache.SourceCache` so we don't hammer the
unauthenticated rate limit (60 requests/hour).

Authenticated access via a personal token can be added later — kept out of
v0.5.0-alpha to avoid exposing credentials in config.json before the UI has
a proper secret store.
"""

import json

from carton.compat_urllib import urlopen, Request, URLError


_API_BASE = "https://api.github.com"
_RAW_BASE = "https://raw.githubusercontent.com"
_ARCHIVE_BASE = "https://github.com"


class GithubApiError(RuntimeError):
    """Raised on network / parse failures or unexpected GitHub responses."""


def _split_repo(repo):
    """Split ``owner/repo`` into a tuple. Validates form."""
    if not repo or "/" not in repo:
        raise GithubApiError("invalid repo {!r}; expected 'owner/repo'".format(repo))
    owner, name = repo.split("/", 1)
    if not owner or not name or "/" in name:
        raise GithubApiError("invalid repo {!r}; expected 'owner/repo'".format(repo))
    return owner, name


def _conditional_get_json(url, cache=None, accept="application/vnd.github+json",
                          timeout=15):
    """GET ``url`` returning parsed JSON, with cache + ETag conditional fetch.

    Returns ``(data, from_cache)``. ``data`` is None on hard failure (caller
    decides how to react). Cached body is returned both on TTL hit and on
    304 Not Modified responses.
    """
    if cache is not None:
        cached_body, etag = cache.read_api(url)
        if cached_body is not None:
            return cached_body, True
    else:
        etag = ""

    req = Request(url)
    req.add_header("Accept", accept)
    req.add_header("User-Agent", "Carton/0.5")
    if etag:
        req.add_header("If-None-Match", etag)

    try:
        resp = urlopen(req, timeout=timeout)
    except URLError as e:
        # 304 surfaces here in some Python configs (urllib treats it as
        # an HTTPError). Try to grab the cached body if we still have it
        # in the cache file (even if expired by TTL).
        if cache is not None and getattr(e, "code", None) == 304:
            cached_body, _ = cache.read_api(url)
            if cached_body is not None:
                return cached_body, True
        raise GithubApiError("GitHub API request failed: {}".format(e))
    except OSError as e:
        raise GithubApiError("GitHub API request failed: {}".format(e))

    new_etag = ""
    try:
        new_etag = resp.headers.get("ETag", "") or ""
    except Exception:
        pass

    try:
        body = json.loads(resp.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise GithubApiError("GitHub API returned invalid JSON: {}".format(e))

    if cache is not None:
        try:
            cache.write_api(url, body, etag=new_etag)
        except OSError:
            pass

    return body, False


def get_default_branch(repo, cache=None):
    """Return the default branch name (e.g. ``"main"``) for a repo."""
    owner, name = _split_repo(repo)
    url = "{}/repos/{}/{}".format(_API_BASE, owner, name)
    data, _ = _conditional_get_json(url, cache=cache)
    if not isinstance(data, dict):
        raise GithubApiError("unexpected /repos response shape")
    return data.get("default_branch") or "main"


def list_releases(repo, cache=None):
    """Return the list of releases for ``repo``.

    Each entry is the raw GitHub Release object. Drafts and pre-releases
    are filtered by the caller — Carton wants stable + pre-release tags
    visible by default so that early-access users can install pre-releases
    explicitly.
    """
    owner, name = _split_repo(repo)
    url = "{}/repos/{}/{}/releases?per_page=100".format(_API_BASE, owner, name)
    data, _ = _conditional_get_json(url, cache=cache)
    if not isinstance(data, list):
        raise GithubApiError("unexpected /releases response shape")
    return data


def list_tags(repo, cache=None):
    """Return the list of git tags for ``repo``.

    Used as a fallback when a repo doesn't publish GitHub Releases —
    tags-only repos are common for tools maintained outside the
    Releases UI.
    """
    owner, name = _split_repo(repo)
    url = "{}/repos/{}/{}/tags?per_page=100".format(_API_BASE, owner, name)
    data, _ = _conditional_get_json(url, cache=cache)
    if not isinstance(data, list):
        raise GithubApiError("unexpected /tags response shape")
    return data


def archive_url_for_tag(repo, tag):
    """Return the URL to GitHub's auto-generated source zip for ``tag``."""
    owner, name = _split_repo(repo)
    return "{}/{}/{}/archive/refs/tags/{}.zip".format(
        _ARCHIVE_BASE, owner, name, tag
    )


def archive_url_for_branch(repo, branch):
    """Return the URL to GitHub's auto-generated source zip for ``branch``."""
    owner, name = _split_repo(repo)
    return "{}/{}/{}/archive/refs/heads/{}.zip".format(
        _ARCHIVE_BASE, owner, name, branch
    )


def raw_file_url(repo, ref, path):
    """Return the URL to a raw file in a repo at a specific ref.

    Used to fetch a repo's ``package.json`` at the default branch when
    detecting whether a GitHub URL points at a single-package source.
    """
    owner, name = _split_repo(repo)
    return "{}/{}/{}/{}/{}".format(_RAW_BASE, owner, name, ref, path)


def fetch_raw_text(url, timeout=15):
    """GET a raw URL and return the body decoded as UTF-8.

    Returns ``""`` on any failure — callers treat empty as "not found"
    rather than special-casing every error path.
    """
    try:
        req = Request(url)
        req.add_header("User-Agent", "Carton/0.5")
        resp = urlopen(req, timeout=timeout)
        return resp.read().decode("utf-8")
    except (URLError, OSError, UnicodeDecodeError):
        return ""


def normalise_version_from_tag(tag):
    """Strip a leading ``v`` from a tag like ``v1.0.0`` → ``1.0.0``.

    Returns the tag unchanged if it doesn't match the ``v?<digits>``
    convention; downstream version parsing handles validation.
    """
    if not tag:
        return tag
    if tag.startswith(("v", "V")) and len(tag) > 1 and tag[1].isdigit():
        return tag[1:]
    return tag
