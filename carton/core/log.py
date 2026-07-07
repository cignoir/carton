"""Central logger for Carton core.

Maya's Script Editor displays stdout, so the default handler writes
there with the same ``[Carton]`` prefix the historical ``print()``
calls used — but through :mod:`logging`, so a host or test can raise
the level, add handlers, or redirect the stream instead of being stuck
with unconditional prints.

Best-effort failure paths (profile mirroring, rollback cleanup, …)
must never be silent: swallowing an exception without a log line is
how user data quietly fails to persist. ``get_logger().warning(...)``
is the minimum viable surface for those.
"""

import logging
import sys

_LOGGER_NAME = "carton"


def get_logger():
    """Return the shared "carton" logger, configuring it on first use."""
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[Carton] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        # Don't double-print through the root logger if the host app
        # (or a test runner) configured one.
        logger.propagate = False
    return logger
