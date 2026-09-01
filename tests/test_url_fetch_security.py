"""Regression tests for url_fetch.py's security-hardening behavior:
scheme restriction (blocks file:// and other non-http(s) URLs) and proxy
routing (the privacy kill switch). Pure stdlib/unittest.mock -- no Qt, no
real network access anywhere in this file.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from torrent2000.config.settings import ProxySettings
from torrent2000.engine.url_fetch import FetchError, fetch_url


def _fake_response(body: bytes = b"ok"):
    # fetch_url() now reads in chunks via response.read(size) (see
    # _read_response_body) rather than one no-arg response.read() call, so
    # this needs to behave like a real file-like object: return up to `size`
    # bytes per call, then b"" once exhausted -- not the same `body` forever,
    # which would never signal EOF and would hang the caller's read loop
    # until it hit the overall deadline.
    import io

    context = MagicMock()
    buf = io.BytesIO(body)
    context.read.side_effect = buf.read
    # Some tests reuse the same mocked response across multiple fetch_url()
    # calls (one shared `context`) -- reset the buffer's read position on
    # each `with ... as response:` entry so every call sees the full body
    # again, the way a fresh HTTP response would.
    def _enter():
        buf.seek(0)
        return context

    context.__enter__.side_effect = _enter
    context.__exit__.return_value = False
    return context


# --------------------------------------------------------------- scheme restriction


def test_file_scheme_is_rejected_and_never_touches_urlopen(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret local content", encoding="utf-8")

    with patch("torrent2000.engine.url_fetch.urllib.request.urlopen") as mock_urlopen:
        with pytest.raises(FetchError):
            fetch_url(secret.as_uri(), "UA/1.0", 5)
        mock_urlopen.assert_not_called()


@pytest.mark.parametrize("url", ["ftp://example.com/file", "data:text/plain,hello", "not-a-url-at-all"])
def test_non_http_schemes_are_rejected(url):
    with patch("torrent2000.engine.url_fetch.urllib.request.urlopen") as mock_urlopen:
        with pytest.raises(FetchError):
            fetch_url(url, "UA/1.0", 5)
        mock_urlopen.assert_not_called()


def test_http_and_https_schemes_are_allowed_through_to_urlopen():
    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen", return_value=_fake_response(b"payload")
    ) as mock_urlopen:
        assert fetch_url("https://example.com/feed.xml", "UA/1.0", 5) == b"payload"
        assert fetch_url("http://example.com/feed.xml", "UA/1.0", 5) == b"payload"
    assert mock_urlopen.call_count == 2


# ------------------------------------------------------------------- proxy routing


def test_proxy_none_uses_direct_urlopen_unchanged():
    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen", return_value=_fake_response(b"payload")
    ) as mock_urlopen:
        assert fetch_url("https://example.com", "UA/1.0", 5, proxy=None) == b"payload"
    mock_urlopen.assert_called_once()


def test_proxy_disabled_uses_direct_urlopen_unchanged():
    proxy = ProxySettings(enabled=False, proxy_type="http", host="proxy.example.com", port=8080)
    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen", return_value=_fake_response(b"payload")
    ) as mock_urlopen:
        assert fetch_url("https://example.com", "UA/1.0", 5, proxy=proxy) == b"payload"
    mock_urlopen.assert_called_once()


def test_http_proxy_without_auth_builds_unauthenticated_proxy_url():
    proxy = ProxySettings(enabled=True, proxy_type="http", host="proxy.example.com", port=8080)
    fake_opener = MagicMock()
    fake_opener.open.return_value = _fake_response(b"payload")

    with patch("torrent2000.engine.url_fetch.urllib.request.build_opener", return_value=fake_opener) as mock_build:
        assert fetch_url("https://example.com", "UA/1.0", 5, proxy=proxy) == b"payload"

    mock_build.assert_called_once()
    handler = mock_build.call_args[0][0]
    assert handler.proxies == {
        "http": "http://proxy.example.com:8080",
        "https": "http://proxy.example.com:8080",
    }
    fake_opener.open.assert_called_once()


def test_http_proxy_with_auth_embeds_credentials_in_proxy_url():
    proxy = ProxySettings(
        enabled=True,
        proxy_type="http_pw",
        host="proxy.example.com",
        port=3128,
        username="alice",
        password="s3cret",
    )
    fake_opener = MagicMock()
    fake_opener.open.return_value = _fake_response(b"payload")

    with patch("torrent2000.engine.url_fetch.urllib.request.build_opener", return_value=fake_opener) as mock_build:
        assert fetch_url("https://example.com", "UA/1.0", 5, proxy=proxy) == b"payload"

    handler = mock_build.call_args[0][0]
    assert handler.proxies == {
        "http": "http://alice:s3cret@proxy.example.com:3128",
        "https": "http://alice:s3cret@proxy.example.com:3128",
    }


def test_socks5_with_force_proxy_raises_without_attempting_any_connection():
    proxy = ProxySettings(enabled=True, proxy_type="socks5", host="proxy.example.com", port=1080, force_proxy=True)

    with patch("torrent2000.engine.url_fetch.urllib.request.urlopen") as mock_urlopen, patch(
        "torrent2000.engine.url_fetch.urllib.request.build_opener"
    ) as mock_build:
        with pytest.raises(FetchError):
            fetch_url("https://example.com", "UA/1.0", 5, proxy=proxy)
        mock_urlopen.assert_not_called()
        mock_build.assert_not_called()


def test_socks5_without_force_proxy_falls_back_to_unproxied_with_warning(caplog):
    proxy = ProxySettings(
        enabled=True, proxy_type="socks5_pw", host="proxy.example.com", port=1080, force_proxy=False
    )

    with caplog.at_level(logging.WARNING, logger="torrent2000.engine.url_fetch"):
        with patch(
            "torrent2000.engine.url_fetch.urllib.request.urlopen", return_value=_fake_response(b"payload")
        ) as mock_urlopen:
            assert fetch_url("https://example.com", "UA/1.0", 5, proxy=proxy) == b"payload"

    mock_urlopen.assert_called_once()
    assert any("SOCKS5" in record.message for record in caplog.records)


# --------------------------------------------------------- response limits
# Regression tests for a defensive pentest finding: fetch_url() used to
# response.read() the entire body with no size cap and a per-socket-op
# timeout that never bounded the whole transfer (a slow drip-feed server
# could stall a caller indefinitely). See security_test/test_rss_attacks.py
# and the published pentest report for the original PoC against a real
# local malicious server.


def test_oversized_response_is_rejected_without_buffering_it_all(monkeypatch):
    import torrent2000.engine.url_fetch as url_fetch_module

    monkeypatch.setattr(url_fetch_module, "_MAX_RESPONSE_BYTES", 10)
    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen",
        return_value=_fake_response(b"this body is way more than ten bytes long"),
    ):
        with pytest.raises(FetchError, match="maximum allowed size"):
            fetch_url("https://example.com", "UA/1.0", 5)


def test_response_that_never_finishes_within_budget_times_out(monkeypatch):
    """Each individual response.read() call returns promptly (so urlopen's
    own per-operation timeout is never tripped), but the fake clock advances
    past the overall deadline between calls -- reproducing a slow drip-feed
    server without an real-time sleep in the test."""
    import torrent2000.engine.url_fetch as url_fetch_module

    fake_now = [0.0]

    def fake_monotonic():
        fake_now[0] += 1.0
        return fake_now[0]

    monkeypatch.setattr(url_fetch_module.time, "monotonic", fake_monotonic)

    response = MagicMock()
    response.read.return_value = b"x"  # always "makes progress", never reaches EOF
    response.__enter__.return_value = response
    response.__exit__.return_value = False

    with patch("torrent2000.engine.url_fetch.urllib.request.urlopen", return_value=response):
        with pytest.raises(FetchError, match="too long"):
            fetch_url("https://example.com", "UA/1.0", timeout_seconds=5)
