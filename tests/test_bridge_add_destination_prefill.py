"""Coverage for AddBridge's new destination auto-prefill on manual add
(selectTorrentFile/_on_metadata_received now call resolve_destination(),
matching what rss_feed_service.py already did automatically -- see
ui/web/bridge_add.py's module docstring). Real-torrent helper mirrors
test_watch_folder_service_routing.py's _write_real_torrent."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.routing_rules import RoutingRule, RoutingRuleStore
from torrent2000.ui.web.bridge_add import AddBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path_factory.mktemp("data_dir")))


class FakeSessionManager(QObject):
    metadata_received = Signal(str)
    download_blocked_by_theme = Signal(str)

    def __init__(self):
        super().__init__()
        self.records = {}

    def get_record(self, info_hash):
        return self.records.get(info_hash)

    def get_torrent_files(self, info_hash):
        return []


class FakeRecord:
    def __init__(self, name):
        self.name = name


def _write_real_torrent(path) -> None:
    payload_dir = path.parent / f"{path.stem}_payload"
    payload_dir.mkdir(exist_ok=True)
    payload_path = payload_dir / "file.txt"
    payload_path.write_bytes(b"hello world")

    fs = lt.file_storage()
    lt.add_files(fs, str(payload_path))
    ct = lt.create_torrent(fs, 0, flags=lt.create_torrent.v1_only)
    lt.set_piece_hashes(ct, str(payload_path.parent))
    path.write_bytes(lt.bencode(ct.generate()))


def _make_bridge():
    session_manager = FakeSessionManager()
    settings = Settings()
    routing_rule_store = RoutingRuleStore()
    bridge = AddBridge(session_manager, settings, routing_rule_store)
    return bridge, session_manager, routing_rule_store


def test_select_torrent_file_suggests_destination_from_a_matching_routing_rule(tmp_path):
    bridge, _sm, routing_rule_store = _make_bridge()
    routing_rule_store.save_rule(
        RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux")
    )
    torrent_path = tmp_path / "ubuntu-24.04-server.torrent"
    _write_real_torrent(torrent_path)

    payloads = []
    bridge.scanReady.connect(payloads.append)

    bridge.selectTorrentFile(str(torrent_path))

    assert len(payloads) == 1
    assert payloads[0]["suggestedDestination"] == "D:/linux"


def test_select_torrent_file_falls_back_to_default_when_no_rule_matches(tmp_path):
    bridge, _sm, _routing_rule_store = _make_bridge()
    torrent_path = tmp_path / "something-else.torrent"
    _write_real_torrent(torrent_path)

    payloads = []
    bridge.scanReady.connect(payloads.append)

    bridge.selectTorrentFile(str(torrent_path))

    assert payloads[0]["suggestedDestination"] == bridge._settings.default_download_dir


def test_metadata_received_suggests_destination_from_the_torrent_record_name():
    bridge, session_manager, routing_rule_store = _make_bridge()
    routing_rule_store.save_rule(
        RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux")
    )
    session_manager.records["hash1"] = FakeRecord("Ubuntu.24.04.Server")
    bridge._pending_magnet_hash = "hash1"

    payloads = []
    bridge.scanReady.connect(payloads.append)

    session_manager.metadata_received.emit("hash1")

    assert len(payloads) == 1
    assert payloads[0]["suggestedDestination"] == "D:/linux"


def test_metadata_received_falls_back_to_default_when_no_rule_matches():
    bridge, session_manager, _routing_rule_store = _make_bridge()
    session_manager.records["hash1"] = FakeRecord("Something.Else")
    bridge._pending_magnet_hash = "hash1"

    payloads = []
    bridge.scanReady.connect(payloads.append)

    session_manager.metadata_received.emit("hash1")

    assert payloads[0]["suggestedDestination"] == bridge._settings.default_download_dir
