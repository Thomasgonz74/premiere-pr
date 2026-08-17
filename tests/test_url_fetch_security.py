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
    context = MagicMock()
    context.read.return_value = body
    context.__enter__.return_value = context
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
