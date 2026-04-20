"""Origin abstraction — where a package's bytes physically live.

A catalogue lists packages by id, but the artifact itself can come from
different places: embedded in the catalogue's own ``packages/`` directory,
a GitHub repo's Releases / Tags, a raw URL, or a local filesystem path.

Each :class:`Origin` subclass knows how to:

* Enumerate the versions available at that origin.
* Resolve a specific version into an :class:`ArtifactRef` (URL + integrity).

Carton's downloader / installer treat all origins uniformly via this layer.
"""

from carton.core.origins.base import (
    ArtifactRef,
    Origin,
    OriginError,
    VersionMeta,
    origin_from_dict,
)
from carton.core.origins.embedded_origin import EmbeddedOrigin
from carton.core.origins.github_origin import GithubOrigin
from carton.core.origins.local_origin import LocalOrigin
from carton.core.origins.url_origin import UrlOrigin


__all__ = [
    "ArtifactRef",
    "EmbeddedOrigin",
    "GithubOrigin",
    "LocalOrigin",
    "Origin",
    "OriginError",
    "UrlOrigin",
    "VersionMeta",
    "origin_from_dict",
]
