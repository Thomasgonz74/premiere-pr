"""ProfileNetworkBridge's remote-access port field (see
ui/web/bridge_profile_network.py), against a real RemoteAccessServer."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import socket

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.remote_server import RemoteAccessServer
from torrent2000.ui.web.bridge_profile_network import ProfileNetworkBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class FakeSessionManager(QObject):
    metadata_received = Signal(str)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_port_change_rebinds_the_running_server():
    # Otherwise the URL shown for the phone names a port nothing listens on
    # until remote access is switched off and on again.
    settings = Settings()
    settings.remote_access_port = 0  # OS-assigned
    session_manager = FakeSessionManager()
    server = RemoteAccessServer(session_manager, settings)
    bridge = ProfileNetworkBridge(session_manager, settings, server)
    assert bridge.setRemoteAccessEnabled(True)["ok"]
    new_port = _free_port()
    try:
        assert bridge.setRemoteAccessPort(new_port) == {"ok": True}
        assert server.bound_port == new_port
        assert bridge.getRemoteAccessInfo()["url"] == f"http://localhost:{new_port}"
    finally:
        server.stop()


@pytest.mark.parametrize("bad_port", [70000, -1, 0])
def test_an_out_of_range_port_is_refused_and_leaves_the_server_running(bad_port):
    # bind() raises OverflowError past 65535 (the slot used to stop the
    # server and raise), and 0 binds a random port the URL can't name.
    settings = Settings()
    settings.remote_access_port = _free_port()
    session_manager = FakeSessionManager()
    server = RemoteAccessServer(session_manager, settings)
    bridge = ProfileNetworkBridge(session_manager, settings, server)
    assert bridge.setRemoteAccessEnabled(True)["ok"]
    old_port = server.bound_port
    try:
        result = bridge.setRemoteAccessPort(bad_port)
        assert result["ok"] is False and result["error"]
        assert server.bound_port == old_port
        assert settings.remote_access_port == old_port
        assert bridge.getRemoteAccessInfo()["url"] == f"http://localhost:{old_port}"
    finally:
        server.stop()


def test_a_saved_port_past_65535_fails_start_instead_of_raising():
    # e.g. config.json edited by hand: the launch must not die on it.
    settings = Settings()
    settings.remote_access_port = 70000
    server = RemoteAccessServer(FakeSessionManager(), settings)
    assert server.start() is False
    assert not server.is_running
