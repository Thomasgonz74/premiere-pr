"""End-to-end tests for engine/remote_server.py -- these hit a real
ThreadingHTTPServer over real HTTP (urllib against 127.0.0.1), not a mocked
protocol, to actually prove the token gate and routing work. Every test
binds on port 0 (OS-assigned) via Settings.remote_access_port = 0 rather
than the real default port, so a parallel test run never collides on a
fixed port.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import pytest

from torrent2000.config.settings import Settings
from torrent2000.engine.remote_server import RemoteAccessServer
from torrent2000.engine.torrent_item import TorrentState


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    # RemoteAccessServer.start() calls Settings.save() the first time it
    # generates a token -- must never write to the real user's config file.
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


@dataclass
class FakeRecord:
    info_hash: str
    name: str = "Some.Linux.Distro.iso"
    progress: float = 0.5
    state: TorrentState = TorrentState.DOWNLOADING
    download_rate: int = 1000
    upload_rate: int = 500


class FakeSessionManager:
    def __init__(self):
        self.records: list = []
        self.paused: list[str] = []
        self.resumed: list[str] = []

    def all_records(self):
        return list(self.records)

    def pause_torrent(self, info_hash: str) -> None:
        self.paused.append(info_hash)

    def resume_torrent(self, info_hash: str) -> None:
        self.resumed.append(info_hash)


def _settings() -> Settings:
    settings = Settings()
    settings.remote_access_port = 0  # OS-assigned -- see module docstring
    return settings


@pytest.fixture
def running_server():
    settings = _settings()
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(info_hash="abc123")]
    server = RemoteAccessServer(fake_sm, settings)
    server.start()
    assert server.is_running
    yield server, fake_sm, settings
    server.stop()


def _url(server: RemoteAccessServer, path: str) -> str:
    return f"http://127.0.0.1:{server.bound_port}{path}"


def _request(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


# ------------------------------------------------------------------ token gate


def test_request_without_token_is_rejected(running_server):
    server, _fake_sm, _settings = running_server
    status, _body = _request(_url(server, "/api/torrents"))
    assert status == 401


def test_request_with_wrong_token_is_rejected(running_server):
    server, _fake_sm, _settings = running_server
    status, _body = _request(_url(server, "/api/torrents?token=totally-wrong"))
    assert status == 401


def test_html_page_also_requires_a_token(running_server):
    server, _fake_sm, settings = running_server
    status, _body = _request(_url(server, "/"))
    assert status == 401

    status, body = _request(_url(server, f"/?token={settings.remote_access_token}"))
    assert status == 200
    assert b"<html" in body.lower()


# --------------------------------------------------------------- torrent list


def test_valid_token_returns_json_torrent_list(running_server):
    server, _fake_sm, settings = running_server
    status, body = _request(_url(server, f"/api/torrents?token={settings.remote_access_token}"))

    assert status == 200
    data = json.loads(body)
    assert data == {
        "torrents": [
            {
                "info_hash": "abc123",
                "name": "Some.Linux.Distro.iso",
                "progress": 0.5,
                "state": "DOWNLOADING",
                "download_rate": 1000,
                "upload_rate": 500,
            }
        ]
    }


# -------------------------------------------------------------- pause/resume


def test_pause_calls_session_manager_with_the_right_info_hash(running_server):
    server, fake_sm, settings = running_server
    status, body = _request(
        _url(server, f"/api/torrents/abc123/pause?token={settings.remote_access_token}"), method="POST"
    )

    assert status == 200
    assert json.loads(body) == {"ok": True}
    assert fake_sm.paused == ["abc123"]
    assert fake_sm.resumed == []


def test_resume_calls_session_manager_with_the_right_info_hash(running_server):
    server, fake_sm, settings = running_server
    status, body = _request(
        _url(server, f"/api/torrents/abc123/resume?token={settings.remote_access_token}"), method="POST"
    )

    assert status == 200
    assert json.loads(body) == {"ok": True}
    assert fake_sm.resumed == ["abc123"]
    assert fake_sm.paused == []


def test_pause_without_a_valid_token_never_reaches_session_manager(running_server):
    server, fake_sm, _settings = running_server
    status, _body = _request(_url(server, "/api/torrents/abc123/pause"), method="POST")

    assert status == 401
    assert fake_sm.paused == []


def test_pause_with_wrong_token_never_reaches_session_manager(running_server):
    server, fake_sm, _settings = running_server
    status, _body = _request(_url(server, "/api/torrents/abc123/pause?token=nope"), method="POST")

    assert status == 401
    assert fake_sm.paused == []


# ---------------------------------------------------------------- token setup


def test_token_is_generated_and_persisted_on_first_start():
    settings = _settings()
    assert settings.remote_access_token == ""
    fake_sm = FakeSessionManager()
    server = RemoteAccessServer(fake_sm, settings)

    server.start()
    try:
        assert settings.remote_access_token != ""
        assert len(settings.remote_access_token) > 20
    finally:
        server.stop()


def test_existing_token_is_not_replaced_by_a_restart():
    settings = _settings()
    fake_sm = FakeSessionManager()
    server = RemoteAccessServer(fake_sm, settings)
    server.start()
    first_token = settings.remote_access_token
    server.stop()

    server.start()
    try:
        assert settings.remote_access_token == first_token
    finally:
        server.stop()


# -------------------------------------------------------------------- lifecycle


def test_stop_is_fast_and_leaves_no_zombie_thread():
    settings = _settings()
    fake_sm = FakeSessionManager()
    server = RemoteAccessServer(fake_sm, settings)
    server.start()
    thread = server._thread
    assert thread is not None
    assert thread.is_alive()

    started_at = time.monotonic()
    server.stop()
    elapsed = time.monotonic() - started_at

    assert elapsed < 5
    assert not thread.is_alive()
    assert not server.is_running


def test_stop_without_start_is_a_harmless_noop():
    settings = _settings()
    fake_sm = FakeSessionManager()
    server = RemoteAccessServer(fake_sm, settings)

    server.stop()  # must not raise

    assert not server.is_running


def test_start_returns_false_and_leaves_is_running_false_on_bind_failure():
    # Regression test: start() must report failure to its caller (rather
    # than only logging it) so UI code can't mistake a provisioned token for
    # a server that's actually listening -- see
    # ui/widgets/remote_access_section.py's own regression test for the
    # caller-side half of this.
    #
    # A plain, non-SO_REUSEADDR socket occupies the port -- ThreadingHTTPServer
    # itself sets SO_REUSEADDR, so using a second RemoteAccessServer as the
    # occupant would not reliably collide on all platforms.
    import socket

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("0.0.0.0", 0))  # same interface RemoteAccessServer binds (_BIND_HOST)
    blocker.listen(1)
    occupied_port = blocker.getsockname()[1]

    settings = _settings()
    settings.remote_access_port = occupied_port
    server = RemoteAccessServer(FakeSessionManager(), settings)
    try:
        assert server.start() is False
        assert not server.is_running
        # The token is still provisioned (see start()'s docstring) -- proves
        # callers cannot use "token exists" as a proxy for "server running".
        assert settings.remote_access_token != ""
    finally:
        server.stop()
        blocker.close()


def test_start_twice_is_idempotent():
    settings = _settings()
    fake_sm = FakeSessionManager()
    server = RemoteAccessServer(fake_sm, settings)
    server.start()
    port_after_first_start = server.bound_port

    server.start()  # must not raise, must not rebind

    assert server.bound_port == port_after_first_start
    server.stop()
