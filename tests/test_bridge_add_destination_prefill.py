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
from torrent2000.engine.session_manager import TorrentAlreadyPresentError
from torrent2000.i18n.translator import tr
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


def test_dropped_torrent_suggests_destination_from_its_dropped_name(tmp_path):
    import base64

    bridge, _sm, routing_rule_store = _make_bridge()
    routing_rule_store.save_rule(
        RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux")
    )
    torrent_path = tmp_path / "source.torrent"
    _write_real_torrent(torrent_path)

    payloads = []
    bridge.scanReady.connect(payloads.append)

    # The drop is written to a "dropped_xxxx.torrent" temp file first.
    temp_path = bridge.saveDroppedTorrent(
        "ubuntu-24.04.torrent", base64.b64encode(torrent_path.read_bytes()).decode()
    )
    try:
        bridge.selectTorrentFile(temp_path)
    finally:
        os.remove(temp_path)

    assert payloads[0]["suggestedDestination"] == "D:/linux"


class FakeMagnetRecord(FakeRecord):
    def __init__(self, name, save_path):
        super().__init__(name)
        self.save_path = save_path


def test_starting_an_analyzed_magnet_moves_it_to_the_chosen_destination(tmp_path):
    bridge, session_manager, _routing_rule_store = _make_bridge()
    default = bridge._settings.default_download_dir
    session_manager.records["hash1"] = FakeMagnetRecord("Ubuntu", default)
    moves = []
    session_manager.move_storage = lambda info_hash, path, quiet=False: moves.append((info_hash, path, quiet))
    session_manager.start_after_analysis = lambda info_hash: None
    bridge._pending_magnet_hash = "hash1"
    destination = str(tmp_path / "linux")

    assert bridge.startTorrent(destination, "", "", []) == {"ok": True}

    # Quiet: placing a magnet being added is no "move finished" toast.
    assert moves == [("hash1", destination, True)]


def test_a_magnet_is_not_started_toward_a_folder_that_cannot_be_used(tmp_path):
    """The move failed in the background (a drive not plugged in) and it
    downloaded into the default folder unannounced -- nor is a drive root,
    which move_storage refuses, any better."""
    bridge, session_manager, _routing_rule_store = _make_bridge()
    session_manager.records["hash1"] = FakeMagnetRecord("DeltaClip", bridge._settings.default_download_dir)
    started = []
    session_manager.move_storage = lambda *args, **kwargs: started.append("moved")
    session_manager.start_after_analysis = started.append
    bridge._pending_magnet_hash = "hash1"
    (tmp_path / "a-file").write_text("")

    unusable = bridge.startTorrent(str(tmp_path / "a-file" / "Films"), "", "", [])
    drive_root = bridge.startTorrent("D:/", "", "", [])

    assert unusable["ok"] is False and unusable["error"].startswith(tr("web.add.destination_unusable", error=""))
    assert drive_root == {"ok": False, "error": tr(
        "notifications.move_storage_refused_message", name="DeltaClip", path="D:/"
    )}
    assert started == [] and bridge._pending_magnet_hash == "hash1"  # still waiting for a usable folder


def test_a_magnet_start_shows_why_it_could_not_be_analysed():
    """The "already present" (or libtorrent's) error flashed by, replaced by
    "Analyse en cours — cliquez de nouveau sur Démarrer": each click the same."""
    bridge, session_manager, _routing_rule_store = _make_bridge()
    session_manager.records["hash1"] = FakeMagnetRecord("HotelFile", "C:/dl")
    session_manager.records["hash1"].awaiting_analysis = False  # live, not a held magnet

    def add_torrent_from_magnet(uri, save_path=None):
        if "zzzz" in uri:
            raise RuntimeError("invalid info-hash [libtorrent:39]")
        raise TorrentAlreadyPresentError("hash1")

    session_manager.add_torrent_from_magnet = add_torrent_from_magnet

    duplicate = bridge.startTorrent("", "magnet:?xt=urn:btih:" + "a4" * 20, "", [])
    invalid = bridge.startTorrent("", "magnet:?xt=urn:btih:zzzz", "", [])

    assert duplicate == {"ok": False, "error": tr("add_tab.duplicate_message")}
    assert invalid == {"ok": False, "error": tr("web.add.magnet_error", error="invalid info-hash [libtorrent:39]")}


def test_a_search_result_torrent_is_routed_by_its_title(tmp_path):
    """Fetched to "search_xxxx.torrent", it was matched against that name:
    the default folder, never the routing rule's."""
    bridge, _sm, routing_rule_store = _make_bridge()
    routing_rule_store.save_rule(
        RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux")
    )
    torrent_path = tmp_path / "search_0lu5u8.torrent"
    _write_real_torrent(torrent_path)
    payloads = []
    bridge.scanReady.connect(payloads.append)

    bridge.nameTorrentFile(str(torrent_path), "Ubuntu 24.04 Server")
    bridge.selectTorrentFile(str(torrent_path))

    assert payloads[0]["suggestedDestination"] == "D:/linux"
