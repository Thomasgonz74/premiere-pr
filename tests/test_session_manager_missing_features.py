"""Targeted tests for the 5 missing-feature SessionManager additions:
categories/labels, peer list, magnet URI, speed-over-time history, and full
file-priority replacement (set_file_priorities vs. the one-way exclude_files).
"""

import collections
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.persistence import save_resume_params
from torrent2000.engine.session_manager import FILE_PRIORITY_DEFAULT, FILE_PRIORITY_EXCLUDED, SessionManager
from torrent2000.engine.torrent_categories import TorrentCategoryService
from torrent2000.engine.torrent_item import TorrentRecord

_MAGNET = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=test"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _session_manager_with_mock_handles(**handles):
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    sm._timer = MagicMock()
    sm._resume_save_timer = MagicMock()
    sm._session = MagicMock()
    sm._handles = dict(handles)
    sm._records = {}
    sm._private_flag_checked = set()
    sm._categories = TorrentCategoryService()
    sm._speed_history = {}
    sm._pending_restore_confirmation = set()
    sm.torrent_status_updated = MagicMock()
    sm.torrent_removed = MagicMock()
    sm.storage_moved = MagicMock()
    return sm


def _status_stub(info_hash: str, download_rate: int = 0, upload_rate: int = 0):
    status = MagicMock()
    hashes = MagicMock()
    hashes.has_v1.return_value = True
    hashes.v1 = info_hash
    status.info_hashes = hashes
    status.name = "some.torrent"
    status.save_path = "/downloads"
    status.total_wanted = 0
    status.progress = 0.0
    status.download_rate = download_rate
    status.upload_rate = upload_rate
    status.num_peers = 0
    status.num_seeds = 0
    status.total_download = 0
    status.total_upload = 0
    status.all_time_download = 0
    status.all_time_upload = 0
    status.error = ""
    status.current_tracker = ""
    status.sequential_download = False
    status.queue_position = 0
    status.has_metadata = True
    status.paused = False
    status.state = "downloading"
    return status


# --------------------------------------------------------------- categories


def test_set_torrent_category_updates_record_and_persists():
    sm = _session_manager_with_mock_handles()
    sm._records["hash0"] = TorrentRecord(info_hash="hash0")

    sm.set_torrent_category("hash0", "Movies")

    assert sm._records["hash0"].category == "Movies"
    assert sm._categories.get("hash0") == "Movies"


def test_set_torrent_category_unknown_record_still_persists():
    sm = _session_manager_with_mock_handles()

    sm.set_torrent_category("unknown", "Movies")  # must not raise

    assert sm._categories.get("unknown") == "Movies"


def test_category_persists_and_reloads_via_a_fresh_service_instance():
    service = TorrentCategoryService()
    service.set("hash0", "Movies")

    reloaded = TorrentCategoryService()

    assert reloaded.get("hash0") == "Movies"


def test_category_get_defaults_to_empty_string():
    service = TorrentCategoryService()

    assert service.get("unknown") == ""


def test_category_survives_full_session_restore():
    """A category assigned via set_torrent_category (persisted through
    TorrentCategoryService) must reappear on the restored torrent's record
    after a brand new SessionManager is constructed -- as on the next launch."""
    atp = lt.parse_magnet_uri(_MAGNET)
    atp.save_path = "C:/downloads"
    info_hash = "0123456789abcdef0123456789abcdef01234567"
    save_resume_params(info_hash, atp)
    TorrentCategoryService().set(info_hash, "Movies")

    settings = Settings()
    session_manager = SessionManager(settings)
    try:
        record = session_manager.get_record(info_hash)
        assert record is not None
        assert record.category == "Movies"
    finally:
        session_manager.shutdown(timeout_ms=0)


def test_on_torrent_removed_clears_the_category():
    sm = _session_manager_with_mock_handles()
    sm._categories.set("hash0", "Movies")
    sm._records["hash0"] = TorrentRecord(info_hash="hash0")

    sm._on_torrent_removed("hash0")

    assert sm._categories.get("hash0") == ""


def test_list_categories_returns_sorted_distinct_non_empty_categories():
    sm = _session_manager_with_mock_handles()
    sm._records["a"] = TorrentRecord(info_hash="a", category="Movies")
    sm._records["b"] = TorrentRecord(info_hash="b", category="Music")
    sm._records["c"] = TorrentRecord(info_hash="c", category="Movies")
    sm._records["d"] = TorrentRecord(info_hash="d", category="")

    assert sm.list_categories() == ["Movies", "Music"]


# --------------------------------------------------------------- peer info


def test_get_peer_info_with_no_peers_returns_empty_list():
    handle = MagicMock()
    handle.is_valid.return_value = True
    handle.get_peer_info.return_value = []
    sm = _session_manager_with_mock_handles(hash0=handle)

    assert sm.get_peer_info("hash0") == []


def test_get_peer_info_maps_fields():
    peer = MagicMock()
    peer.ip = ("1.2.3.4", 6881)
    peer.client = "uTorrent"
    peer.progress = 0.5
    peer.payload_down_speed = 1000
    peer.payload_up_speed = 200
    handle = MagicMock()
    handle.is_valid.return_value = True
    handle.get_peer_info.return_value = [peer]
    sm = _session_manager_with_mock_handles(hash0=handle)

    peers = sm.get_peer_info("hash0")

    assert len(peers) == 1
    assert peers[0].ip == "1.2.3.4:6881"
    assert peers[0].client == "uTorrent"
    assert peers[0].progress == 0.5
    assert peers[0].down_speed == 1000
    assert peers[0].up_speed == 200


def test_get_peer_info_missing_handle_returns_empty_list():
    sm = _session_manager_with_mock_handles()

    assert sm.get_peer_info("unknown") == []


def test_get_peer_info_invalid_handle_returns_empty_list():
    handle = MagicMock()
    handle.is_valid.return_value = False
    sm = _session_manager_with_mock_handles(hash0=handle)

    assert sm.get_peer_info("hash0") == []


# --------------------------------------------------------------- magnet uri


def test_get_magnet_uri_missing_handle_returns_none():
    sm = _session_manager_with_mock_handles()

    assert sm.get_magnet_uri("unknown") is None


def test_get_magnet_uri_invalid_handle_returns_none():
    handle = MagicMock()
    handle.is_valid.return_value = False
    sm = _session_manager_with_mock_handles(hash0=handle)

    assert sm.get_magnet_uri("hash0") is None


def test_get_magnet_uri_returns_none_when_libtorrent_call_fails(monkeypatch):
    handle = MagicMock()
    handle.is_valid.return_value = True
    sm = _session_manager_with_mock_handles(hash0=handle)
    monkeypatch.setattr(lt, "make_magnet_uri", MagicMock(side_effect=RuntimeError("boom")))

    assert sm.get_magnet_uri("hash0") is None


def test_get_magnet_uri_returns_uri_from_libtorrent(monkeypatch):
    handle = MagicMock()
    handle.is_valid.return_value = True
    sm = _session_manager_with_mock_handles(hash0=handle)
    monkeypatch.setattr(lt, "make_magnet_uri", MagicMock(return_value="magnet:?xt=urn:btih:abc"))

    assert sm.get_magnet_uri("hash0") == "magnet:?xt=urn:btih:abc"


# --------------------------------------------------------------- speed history


def test_get_speed_history_accumulates_across_ticks():
    handle = MagicMock()
    handle.torrent_file.return_value = None
    sm = _session_manager_with_mock_handles(hash0=handle)
    sm._records["hash0"] = TorrentRecord(info_hash="hash0")

    sm._on_state_update([_status_stub("hash0", download_rate=100, upload_rate=10)])
    sm._on_state_update([_status_stub("hash0", download_rate=200, upload_rate=20)])
    sm._on_state_update([_status_stub("hash0", download_rate=300, upload_rate=30)])

    assert sm.get_speed_history("hash0") == [(100, 10), (200, 20), (300, 30)]


def test_get_speed_history_unknown_hash_returns_empty_list():
    sm = _session_manager_with_mock_handles()

    assert sm.get_speed_history("unknown") == []


def test_on_torrent_removed_clears_speed_history():
    sm = _session_manager_with_mock_handles()
    sm._speed_history["hash0"] = collections.deque([(1, 2)], maxlen=200)
    sm._records["hash0"] = TorrentRecord(info_hash="hash0")

    sm._on_torrent_removed("hash0")

    assert sm.get_speed_history("hash0") == []


# --------------------------------------------------------------- file priorities


def test_set_file_priorities_restores_a_previously_excluded_file():
    handle = MagicMock()
    handle.get_file_priorities.return_value = [FILE_PRIORITY_EXCLUDED, FILE_PRIORITY_DEFAULT, FILE_PRIORITY_DEFAULT]
    sm = _session_manager_with_mock_handles(hash0=handle)

    # Re-include file 0 (previously excluded), exclude file 2 instead.
    sm.set_file_priorities("hash0", {2})

    handle.prioritize_files.assert_called_once_with(
        [FILE_PRIORITY_DEFAULT, FILE_PRIORITY_DEFAULT, FILE_PRIORITY_EXCLUDED]
    )


def test_set_file_priorities_missing_handle_is_a_noop():
    sm = _session_manager_with_mock_handles()

    sm.set_file_priorities("unknown", {0})  # must not raise
