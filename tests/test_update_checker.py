import json
import os
import time
import urllib.error
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000 import APP_VERSION
from torrent2000.config.settings import Settings
from torrent2000.engine.update_checker import UpdateChecker, is_newer_version, parse_version


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------- version parsing


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.2.0", (1, 2, 0)),
        ("v1.2.0", (1, 2, 0)),
        ("V0.1.0", (0, 1, 0)),
        ("1.2.0-beta", (1, 2, 0)),
        ("2.0", (2, 0)),
    ],
)
def test_parse_version(version, expected):
    assert parse_version(version) == expected


@pytest.mark.parametrize(
    "remote,local,expected",
    [
        ("v1.0.0", "0.1.0", True),
        ("0.1.0", "0.1.0", False),
        ("0.0.9", "0.1.0", False),
        ("0.1.1", "0.1.0", True),
        ("v0.2.0", "v0.1.0", True),
    ],
)
def test_is_newer_version(remote, local, expected):
    assert is_newer_version(remote, local) is expected


# --------------------------------------------------------------- UpdateChecker


def _fake_response(payload: dict):
    # fetch_url() reads in chunks via response.read(size) (see
    # url_fetch._read_response_body), so this needs real file-like read()
    # semantics -- b"" once exhausted, not the same body returned forever
    # regardless of the requested size.
    import io

    body = json.dumps(payload).encode("utf-8")
    context = MagicMock()
    buf = io.BytesIO(body)
    context.read.side_effect = buf.read
    context.__enter__.return_value = context
    context.__exit__.return_value = False
    return context


def _run_check_and_wait(app, checker, timeout_s=1.0, until=None):
    # `until` lets a positive-result test return the moment its signal
    # fires rather than always burning the full timeout; negative-result
    # tests (nothing should ever arrive) still wait out the whole window.
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.01)


def test_emits_update_available_for_a_newer_release(qapp):
    settings = Settings()
    checker = UpdateChecker(settings)
    received = []
    checker.update_available.connect(lambda v, u: received.append((v, u)))

    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen",
        return_value=_fake_response(
            {"tag_name": "v99.0.0", "html_url": "https://github.com/Thomasgonz74/premiere-pr/releases/v99.0.0"}
        ),
    ):
        checker.check_now()
        _run_check_and_wait(qapp, checker, until=lambda: received)

    assert received == [("v99.0.0", "https://github.com/Thomasgonz74/premiere-pr/releases/v99.0.0")]


def test_does_not_emit_when_already_up_to_date(qapp):
    settings = Settings()
    checker = UpdateChecker(settings)
    received = []
    checker.update_available.connect(lambda v, u: received.append((v, u)))

    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen",
        return_value=_fake_response({"tag_name": f"v{APP_VERSION}", "html_url": "https://example.com"}),
    ):
        checker.check_now()
        _run_check_and_wait(qapp, checker)

    assert received == []


def test_does_not_emit_for_an_already_dismissed_version(qapp):
    settings = Settings()
    settings.dismissed_update_version = "v99.0.0"
    checker = UpdateChecker(settings)
    received = []
    checker.update_available.connect(lambda v, u: received.append((v, u)))

    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen",
        return_value=_fake_response({"tag_name": "v99.0.0", "html_url": "https://example.com"}),
    ):
        checker.check_now()
        _run_check_and_wait(qapp, checker)

    assert received == []


def test_skips_the_network_call_entirely_when_disabled(qapp):
    settings = Settings()
    settings.check_for_updates = False
    checker = UpdateChecker(settings)

    with patch("torrent2000.engine.url_fetch.urllib.request.urlopen") as mock_urlopen:
        checker.check_now()
        _run_check_and_wait(qapp, checker, timeout_s=0.5)
        mock_urlopen.assert_not_called()


def test_network_failure_does_not_raise_or_emit(qapp):
    settings = Settings()
    checker = UpdateChecker(settings)
    received = []
    checker.update_available.connect(lambda v, u: received.append((v, u)))

    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen",
        side_effect=urllib.error.URLError("no internet"),
    ):
        checker.check_now()  # must not raise
        _run_check_and_wait(qapp, checker)

    assert received == []


def test_malformed_response_does_not_raise_or_emit(qapp):
    settings = Settings()
    checker = UpdateChecker(settings)
    received = []
    checker.update_available.connect(lambda v, u: received.append((v, u)))

    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen",
        return_value=_fake_response({"unexpected": "shape"}),
    ):
        checker.check_now()
        _run_check_and_wait(qapp, checker)

    assert received == []


def test_non_github_html_url_is_treated_as_malformed(qapp):
    # A html_url that doesn't point at github.com is either a bug or a
    # spoofed/compromised response trying to get the app to later open an
    # attacker-controlled page in a browser -- must be rejected exactly like
    # a missing tag_name/html_url, not passed through to update_available.
    settings = Settings()
    checker = UpdateChecker(settings)
    received = []
    checker.update_available.connect(lambda v, u: received.append((v, u)))

    with patch(
        "torrent2000.engine.url_fetch.urllib.request.urlopen",
        return_value=_fake_response({"tag_name": "v99.0.0", "html_url": "https://evil.example.com/releases/v99.0.0"}),
    ):
        checker.check_now()
        _run_check_and_wait(qapp, checker)

    assert received == []


# ------------------------------------------------------------------ proxy passthrough


def test_check_now_passes_settings_proxy_to_fetch_url(qapp):
    settings = Settings()
    settings.proxy.enabled = True
    settings.proxy.proxy_type = "http"
    settings.proxy.host = "proxy.example.com"
    settings.proxy.port = 8080
    checker = UpdateChecker(settings)
    received = []
    checker.update_available.connect(lambda v, u: received.append((v, u)))

    captured_proxies = []

    def fake_fetch_url(url, user_agent, timeout_seconds, extra_headers=None, proxy=None):
        captured_proxies.append(proxy)
        return json.dumps({"tag_name": "v99.0.0", "html_url": "https://github.com/x/y/releases/v99.0.0"}).encode(
            "utf-8"
        )

    with patch("torrent2000.engine.update_checker.fetch_url", fake_fetch_url):
        checker.check_now()
        _run_check_and_wait(qapp, checker, until=lambda: received)

    assert captured_proxies == [settings.proxy]
    assert received == [("v99.0.0", "https://github.com/x/y/releases/v99.0.0")]
