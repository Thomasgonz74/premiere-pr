"""Shared "GET a URL off the GUI thread" primitive for update_checker.py and
rss_feed_service.py -- both submit a QRunnable to QThreadPool.globalInstance()
that does nothing more than an authenticated-by-User-Agent urllib fetch with
a timeout, then hand the raw bytes (or a failure) back to the GUI thread
through their own signal bus. This module owns only that shared fetch step;
each caller keeps its own QRunnable/signals so its own post-processing (JSON
decoding, RSS parsing, writing a downloaded .torrent to disk) still happens
off the GUI thread too, right where the bytes already are.
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from torrent2000.config.settings import ProxySettings

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}

# Generous for an RSS feed or an update-check response -- both are normally
# KB-scale -- while still bounding how much memory a hostile/compromised
# server can force this process to buffer.
_MAX_RESPONSE_BYTES = 50 * 1024 * 1024
_READ_CHUNK_BYTES = 65536


class FetchError(Exception):
    """Raised by fetch_url() for any network/IO failure, so callers catch
    one exception type instead of urllib's several distinct classes."""


def _read_response_body(response, deadline: float, max_bytes: int | None = None) -> bytes:
    """response.read() alone buffers unboundedly and only respects urlopen's
    per-socket-operation timeout, not how long the WHOLE transfer takes -- a
    server that drip-feeds a handful of bytes at a time never trips that
    timeout no matter how long it strings the caller along. This enforces a
    hard size cap and a real wall-clock deadline across the entire read.

    max_bytes defaults to the module-level cap, read fresh on each call
    (rather than bound once at def time) so tests can monkeypatch
    _MAX_RESPONSE_BYTES and have it actually take effect."""
    if max_bytes is None:
        max_bytes = _MAX_RESPONSE_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        if time.monotonic() > deadline:
            raise FetchError("Response took too long to read in full (exceeded overall fetch deadline)")
        chunk = response.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(f"Response exceeded the maximum allowed size ({max_bytes} bytes)")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_url(
    url: str,
    user_agent: str,
    timeout_seconds: float,
    extra_headers: dict | None = None,
    proxy: "ProxySettings | None" = None,
) -> bytes:
    # Python's urllib.request happily opens file:// (and other non-http(s))
    # URLs by default -- without this check, a crafted feed/config URL could
    # read arbitrary local files instead of fetching anything over the
    # network. Reject before urlopen/build_opener ever sees the URL.
    scheme = urlsplit(url).scheme
    if scheme not in _ALLOWED_SCHEMES:
        raise FetchError(f"Refusing to fetch a non-http(s) URL (scheme: {scheme or '<none>'!r})")

    request = urllib.request.Request(url, headers={"User-Agent": user_agent, **(extra_headers or {})})
    opener = _build_proxy_opener(proxy, url)
    # timeout_seconds bounds the WHOLE operation (connect + full read) from
    # here on, not just each individual socket recv() the way urlopen's own
    # timeout= does -- see _read_response_body.
    deadline = time.monotonic() + timeout_seconds

    try:
        if opener is not None:
            with opener.open(request, timeout=timeout_seconds) as response:
                return _read_response_body(response, deadline)
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return _read_response_body(response, deadline)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(str(exc)) from exc


def _build_proxy_opener(proxy: "ProxySettings | None", url: str) -> urllib.request.OpenerDirector | None:
    """Returns an opener routed through the user's configured proxy, or None
    to use the default direct urlopen -- None is also the (unchanged)
    behavior when proxy is absent/disabled, so this stays a no-op for any
    caller that doesn't pass proxy settings."""
    if proxy is None or not proxy.enabled:
        return None

    if proxy.proxy_type in ("http", "http_pw"):
        proxy_url = _build_http_proxy_url(proxy)
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        return urllib.request.build_opener(handler)

    if proxy.proxy_type in ("socks5", "socks5_pw"):
        # Python's stdlib urllib.request has no native SOCKS support (that
        # needs a third-party dependency such as PySocks, which this project
        # deliberately avoids). force_proxy is the user's explicit kill
        # switch -- honor it by refusing the fetch outright rather than
        # silently sending it unproxied.
        if proxy.force_proxy:
            raise FetchError(
                "Cannot route this fetch through the configured SOCKS5 proxy without an optional "
                "dependency; refusing to fetch unproxied because the proxy kill switch (force_proxy) "
                "is enabled."
            )
        logger.warning(
            "SOCKS5 proxy configured but unsupported for this background fetch without an optional "
            "dependency; force_proxy is disabled, so proceeding unproxied for %s",
            url,
        )
        return None

    return None


def _build_http_proxy_url(proxy: "ProxySettings") -> str:
    if proxy.username:
        return f"http://{proxy.username}:{proxy.password}@{proxy.host}:{proxy.port}"
    return f"http://{proxy.host}:{proxy.port}"
