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
