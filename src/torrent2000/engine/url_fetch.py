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

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

# urllib.request/urllib.error are imported inside the functions below, not
# here: they pull in http.client, ssl and email.* (~25 modules), none of
# which is needed before the first network fetch -- and this module is
# imported at startup by every service that fetches anything.
if TYPE_CHECKING:
    import urllib.request

    from torrent2000.config.settings import ProxySettings

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}

# Generous for an RSS feed or an update-check response -- both are normally
# KB-scale -- while still bounding how much memory a hostile/compromised
# server can force this process to buffer.
_MAX_RESPONSE_BYTES = 50 * 1024 * 1024
# fetch_url_to_file's own cap: it streams to disk, so this bounds disk use,
# not memory -- well above the ~130 MB installer (it bundles QtWebEngine).
_MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
# fetch_url_to_file's per-socket-operation timeout (connect, each read): its
# overall deadline is long (600 s for the installer), and a read stalled on
# a dead connection is the one wait cancel_all_fetches() can't cut short.
_DOWNLOAD_SOCKET_TIMEOUT_SECONDS = 30
_READ_CHUNK_BYTES = 65536

# Set once at quit (cancel_all_fetches) so a running download/fetch stops at
# its next chunk instead of keeping the process alive -- Qt waits for every
# running QThreadPool task before the process can exit. Never cleared.
_cancel_event = threading.Event()


class FetchError(Exception):
    """Raised by fetch_url() for any network/IO failure, so callers catch
    one exception type instead of urllib's several distinct classes."""


class FetchCancelled(FetchError):
    """The fetch was stopped by cancel_all_fetches() (the app is quitting),
    not by a network problem -- callers that react to a failure in a
    user-visible way can tell the two apart."""


def cancel_all_fetches() -> None:
    """Called once at quit: every fetch in flight stops at its next chunk
    (raising FetchCancelled) and any later fetch fails before connecting."""
    _cancel_event.set()


def _iter_response_chunks(response, deadline: float, max_bytes: int):
    """response.read() alone buffers unboundedly and only respects urlopen's
    per-socket-operation timeout, not how long the WHOLE transfer takes -- a
    server that drip-feeds a handful of bytes at a time never trips that
    timeout no matter how long it strings the caller along. This enforces a
    hard size cap and a real wall-clock deadline across the entire read,
    and stops at the next chunk once cancel_all_fetches() has been called."""
    total = 0
    while True:
        if _cancel_event.is_set():
            raise FetchCancelled("Fetch cancelled: the application is quitting")
        if time.monotonic() > deadline:
            raise FetchError("Response took too long to read in full (exceeded overall fetch deadline)")
        chunk = response.read(_READ_CHUNK_BYTES)
        if not chunk:
            return
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(f"Response exceeded the maximum allowed size ({max_bytes} bytes)")
        yield chunk


def _read_response_body(response, deadline: float, max_bytes: int | None = None) -> bytes:
    """See _iter_response_chunks. max_bytes defaults to the module-level
    cap, read fresh on each call (rather than bound once at def time) so
    tests can monkeypatch _MAX_RESPONSE_BYTES and have it actually take
    effect."""
    if max_bytes is None:
        max_bytes = _MAX_RESPONSE_BYTES
    return b"".join(_iter_response_chunks(response, deadline, max_bytes))


def _open(
    url: str,
    user_agent: str,
    timeout_seconds: float,
    extra_headers: dict | None = None,
    proxy: "ProxySettings | None" = None,
    data: bytes | None = None,
):
    """Scheme guard, request and proxy routing shared by fetch_url and
    fetch_url_to_file -- returns the open response (a context manager)."""
    import urllib.request

    # Python's urllib.request happily opens file:// (and other non-http(s))
    # URLs by default -- without this check, a crafted feed/config URL could
    # read arbitrary local files instead of fetching anything over the
    # network. Reject before urlopen/build_opener ever sees the URL.
    scheme = urlsplit(url).scheme
    if scheme not in _ALLOWED_SCHEMES:
        raise FetchError(f"Refusing to fetch a non-http(s) URL (scheme: {scheme or '<none>'!r})")
    if _cancel_event.is_set():
        raise FetchCancelled("Fetch cancelled: the application is quitting")

    # urllib.request.Request uses POST automatically when data is not None,
    # GET otherwise -- existing callers never pass data, so this is a purely
    # additive capability (webhook_notification_service.py's POST is the
    # first caller to use it).
    request = urllib.request.Request(url, data=data, headers={"User-Agent": user_agent, **(extra_headers or {})})
    opener = _build_proxy_opener(proxy, url)
    if opener is not None:
        return opener.open(request, timeout=timeout_seconds)
    return urllib.request.urlopen(request, timeout=timeout_seconds)


def fetch_url(
    url: str,
    user_agent: str,
    timeout_seconds: float,
    extra_headers: dict | None = None,
    proxy: "ProxySettings | None" = None,
    data: bytes | None = None,
) -> bytes:
    import urllib.error  # before the try: the except clause below needs it

    # timeout_seconds bounds the WHOLE operation (connect + full read) from
    # here on, not just each individual socket recv() the way urlopen's own
    # timeout= does -- see _iter_response_chunks.
    deadline = time.monotonic() + timeout_seconds
    try:
        with _open(url, user_agent, timeout_seconds, extra_headers, proxy, data) as response:
            return _read_response_body(response, deadline)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(str(exc)) from exc


def fetch_url_to_file(
    url: str,
    user_agent: str,
    timeout_seconds: float,
    dest: Path,
    expected_sha256: str,
    proxy: "ProxySettings | None" = None,
) -> None:
    """Streaming sibling of fetch_url for large downloads (the ~130 MB
    update installer): each chunk goes straight to dest and into an
    incremental SHA-256, so memory holds one chunk instead of the whole body
    (twice, with the join). Same scheme guard, proxy routing and overall
    deadline as fetch_url, with its own size cap (_MAX_DOWNLOAD_BYTES).

    dest only survives a download that completed AND matched
    expected_sha256 -- on a mismatch or any error it is removed before
    FetchError propagates, so no partial or unverified file is left behind."""
    import http.client  # already loaded by urllib.request; for IncompleteRead
    import urllib.error  # before the try: the except clause below needs it

    deadline = time.monotonic() + timeout_seconds
    digest = hashlib.sha256()
    verified = False
    try:
        socket_timeout = min(timeout_seconds, _DOWNLOAD_SOCKET_TIMEOUT_SECONDS)
        with _open(url, user_agent, socket_timeout, proxy=proxy) as response, open(dest, "wb") as out:
            for chunk in _iter_response_chunks(response, deadline, _MAX_DOWNLOAD_BYTES):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != expected_sha256.lower():
            raise FetchError("SHA-256 mismatch")
        verified = True
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
        raise FetchError(str(exc)) from exc
    finally:
        if not verified:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove unverified download %s", dest)


def _build_proxy_opener(proxy: "ProxySettings | None", url: str) -> urllib.request.OpenerDirector | None:
    """Returns an opener routed through the user's configured proxy, or None
    to use the default direct urlopen -- None is also the (unchanged)
    behavior when proxy is absent/disabled, so this stays a no-op for any
    caller that doesn't pass proxy settings."""
    if proxy is None or not proxy.enabled:
        return None

    import urllib.request

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
