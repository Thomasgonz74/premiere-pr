"""AddBridge.startTorrent on a .torrent already in the session, with a real
SessionManager: libtorrent's own duplicate error is English and never empty,
so the bridge has to recognise the case itself to show the translated
message -- and the live torrent's record must survive the attempt."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.routing_rules import RoutingRuleStore
from torrent2000.engine.session_manager import SessionManager, TorrentAlreadyPresentError
from torrent2000.i18n.translator import tr
from torrent2000.ui.web.bridge_add import AddBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path / "appdata"))


def _make_torrent(tmp_path):
    payload = tmp_path / "alpha.bin"
    payload.write_bytes(os.urandom(32 * 1024))
    fs = lt.file_storage()
    lt.add_files(fs, str(payload))
    ct = lt.create_torrent(fs, piece_size=16 * 1024)
    lt.set_piece_hashes(ct, str(tmp_path))
    torrent_path = tmp_path / "alpha.torrent"
    torrent_path.write_bytes(lt.bencode(ct.generate()))
    return torrent_path


def test_adding_a_torrent_already_in_the_session_says_so_and_keeps_its_record(tmp_path):
    torrent_path = _make_torrent(tmp_path)

    settings = Settings()
    settings.network_interface = "127.0.0.1"
    sm = SessionManager(settings)
    try:
        bridge = AddBridge(sm, settings, RoutingRuleStore())
        bridge.selectTorrentFile(str(torrent_path))
        assert bridge.startTorrent(str(tmp_path), "", "mycat", []) == {"ok": True}

        bridge.selectTorrentFile(str(torrent_path))
        result = bridge.startTorrent(str(tmp_path / "elsewhere"), "", "", [])

        records = sm.all_records()
    finally:
        sm.shutdown(timeout_ms=0)

    assert result == {"ok": False, "error": tr("add_tab.duplicate_message")}
    assert [(r.category, r.save_path) for r in records] == [("mycat", str(tmp_path))]


def test_the_duplicate_error_says_what_happened(tmp_path):
    # Its text is the remote API's answer (POST /api/torrents/add, a .torrent).
    torrent_path = _make_torrent(tmp_path)
    settings = Settings()
    settings.network_interface = "127.0.0.1"
    sm = SessionManager(settings)
    try:
        sm.add_torrent_from_file(str(torrent_path), str(tmp_path))
        with pytest.raises(TorrentAlreadyPresentError):
            sm.add_torrent_from_file(str(torrent_path), str(tmp_path))
    finally:
        sm.shutdown(timeout_ms=0)
