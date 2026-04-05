"""Centralized urllib imports for Python 2/3 compatibility.

Maya 2024+ ships Python 3, so the Python 2 fallbacks are kept only as
a safety net for older environments.
"""

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
    from urllib.parse import urljoin, urlparse
except ImportError:
    from urllib2 import urlopen, Request, URLError  # type: ignore[no-redef]
    from urlparse import urljoin, urlparse  # type: ignore[no-redef]

try:
    from io import BytesIO
except ImportError:
    from StringIO import StringIO as BytesIO  # type: ignore[no-redef]

__all__ = ["urlopen", "Request", "URLError", "urljoin", "urlparse", "BytesIO"]
