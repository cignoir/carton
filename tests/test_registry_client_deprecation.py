"""Verify :class:`RegistryClient` now emits a DeprecationWarning.

CatalogueClient has been driving startup since Step 4-A Phase 3
(commit ``b7b7b94``). RegistryClient is kept around only for two
legacy test files that will migrate during Step 4-B; every other
consumer should be on CatalogueClient. The deprecation warning is
the mechanism by which any new caller accidentally importing the
old class gets a visible nudge.

Removal plan: post v0.5.0 rollout, delete ``registry_client.py``
entirely once the two test files are gone (or also migrated).
"""

import warnings

import pytest

from carton.core.config import Config
from carton.core.registry_client import RegistryClient


class TestDeprecationWarning:
    def test_instantiate_emits_warning(self):
        config = Config()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            RegistryClient(config)
        deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecations) == 1
        # The message must name the replacement so readers of their log
        # know where to migrate to.
        assert "CatalogueClient" in str(deprecations[0].message)

    def test_warning_has_caller_stacklevel(self):
        """stacklevel=2 makes the warning blame the caller's line, not
        the inside of __init__ — so when a user sees it in Maya they
        can jump straight to their own code."""
        config = Config()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            RegistryClient(config)  # this is the line we want blamed
        assert len(w) == 1
        # The recorded filename points at this test file, not
        # registry_client.py.
        assert w[0].filename.endswith("test_registry_client_deprecation.py")
