"""Adding a torrent the session already has used to replace its live
TorrentRecord before libtorrent was even asked: category, pin and rule
were lost, and a re-added magnet stuck as AWAITING_ANALYSIS. Clipboard
detection offers exactly that for a magnet the app copied itself."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.danger_scanner.models import FileEntry
from torrent2000.engine.routing_rules import RoutingRuleStore
from torrent2000.engine.session_manager import SessionManager, TorrentAlreadyPresentError
from torrent2000.engine.torrent_item import TorrentRecord
from torrent2000.ui.web.bridge_add import AddBridge

_MAGNET = "magnet:?xt=urn:btih:" + "cd" * 20 + "&dn=twice"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path / "appdata"))


@pytest.fixture
def sm():
    settings = Settings()
    settings.network_interface = "127.0.0.1"
    session_manager = SessionManager(settings)
    yield session_manager
    session_manager.shutdown(timeout_ms=0)


def _torrent_file(tmp_path) -> str:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"x" * 1024)
    fs = lt.file_storage()
    lt.add_files(fs, str(payload))
    ct = lt.create_torrent(fs)
    lt.set_piece_hashes(ct, str(tmp_path))
    path = tmp_path / "payload.torrent"
    path.write_bytes(lt.bencode(ct.generate()))
    return str(path)


def test_re_adding_a_torrent_keeps_its_live_record(sm, tmp_path):
    magnet_hash = sm.add_torrent_from_magnet(_MAGNET, str(tmp_path))
    sm.start_after_analysis(magnet_hash)
    file_hash = sm.add_torrent_from_file(_torrent_file(tmp_path), str(tmp_path))
    for info_hash in (magnet_hash, file_hash):
        sm.set_torrent_category(info_hash, "Films")
        sm.pin_torrent(info_hash)
    records = {ih: sm.get_record(ih) for ih in (magnet_hash, file_hash)}

    with pytest.raises(TorrentAlreadyPresentError):
        sm.add_torrent_from_magnet(_MAGNET, str(tmp_path))
    with pytest.raises(TorrentAlreadyPresentError):
        sm.add_torrent_from_file(_torrent_file(tmp_path), str(tmp_path))

    for info_hash, record in records.items():
        assert sm.get_record(info_hash) is record
        assert record.category == "Films" and record.pinned and not record.awaiting_analysis


def test_the_add_page_picks_back_up_a_magnet_still_awaiting_analysis(sm, tmp_path):
    AddBridge(sm, Settings(), RoutingRuleStore()).analyzeMagnet(_MAGNET)
    (record,) = sm.all_records()
    reopened = AddBridge(sm, Settings(), RoutingRuleStore())  # e.g. after a restart
    statuses = []
    reopened.statusChanged.connect(statuses.append)

    reopened.analyzeMagnet(_MAGNET)

    assert statuses == ["En attente des métadonnées…"]
    assert reopened._pending_magnet_hash == record.info_hash
    assert sm.get_record(record.info_hash) is record


def test_a_magnet_picked_back_up_with_its_metadata_in_is_scanned_at_once():
    """Its metadata_received has come and gone (before a restart, say)."""

    class _SessionManager(QObject):
        metadata_received = Signal(str)
        download_blocked_by_theme = Signal(str)

        def add_torrent_from_magnet(self, uri, save_path=None):
            raise TorrentAlreadyPresentError("ih")

        def get_record(self, info_hash):
            return TorrentRecord(info_hash=info_hash, name="pending", awaiting_analysis=True)

        def get_torrent_files(self, info_hash):
            return [FileEntry(index=0, path="pending/video.mkv", size=1024)]

    bridge = AddBridge(_SessionManager(), Settings(), RoutingRuleStore())
    scans = []
    bridge.scanReady.connect(scans.append)

    bridge.analyzeMagnet(_MAGNET)

    assert len(scans) == 1 and bridge._pending_magnet_hash == "ih"
