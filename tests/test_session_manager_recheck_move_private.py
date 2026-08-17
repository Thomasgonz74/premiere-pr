"""Regression tests for three small SessionManager additions:
recheck_torrent (force_recheck), move_storage (move_storage +
storage_moved_alert bookkeeping), and the lazily-populated
TorrentRecord.is_private flag (only available once handle.torrent_file()
stops returning None).
"""

from unittest.mock import MagicMock

from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState
from torrent2000.theme_ids import CCCP_THEME_ID


def _session_manager_with_mock_handles(**handles):
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    sm._timer = MagicMock()
    sm._resume_save_timer = MagicMock()
    sm._session = MagicMock()
    sm._handles = dict(handles)
    sm._records = {}
    sm._private_flag_checked = set()
    sm._speed_history = {}
    sm.torrent_status_updated = MagicMock()
    sm.storage_moved = MagicMock()
    return sm


def _ghost_handle():
    """A handle whose C++ side is already gone: is_valid() is False and any
    real call (unset_flags, set_flags, pause, resume...) raises like real
    libtorrent does for a stale handle."""
    handle = MagicMock()
    handle.is_valid.return_value = False
    handle.unset_flags.side_effect = RuntimeError("invalid torrent handle used [libtorrent:20]")
    handle.set_flags.side_effect = RuntimeError("invalid torrent handle used [libtorrent:20]")
    return handle


def test_pause_torrent_on_ghost_handle_is_a_no_op():
    sm = _session_manager_with_mock_handles(ghost=_ghost_handle())

    sm.pause_torrent("ghost")  # must not raise


def test_resume_torrent_on_ghost_handle_is_a_no_op():
    sm = _session_manager_with_mock_handles(ghost=_ghost_handle())

    sm.resume_torrent("ghost")  # must not raise


def test_enforce_theme_download_policy_skips_ghost_handles_without_crashing():
    """Regression: a ghost TorrentRecord (stale/invalid handle left behind
    in _records) used to make pause_torrent's handle.unset_flags() raise
    RuntimeError, aborting enforce_theme_download_policy() before the caller
    (GeneralSettingsSection._on_theme_changed) reached theme_changed.emit()
    -- the theme was saved to settings but the UI never actually restyled."""
    sm = _session_manager_with_mock_handles(ghost=_ghost_handle())
    sm._settings = MagicMock()
    sm._settings.theme = CCCP_THEME_ID
    sm.theme_downloads_paused = MagicMock()
    sm._records["ghost"] = TorrentRecord(info_hash="ghost", progress=0.5, state=TorrentState.DOWNLOADING)

    sm.enforce_theme_download_policy()  # must not raise


def test_recheck_torrent_calls_force_recheck_on_the_handle():
    handle = MagicMock()
    sm = _session_manager_with_mock_handles(hash0=handle)

    sm.recheck_torrent("hash0")

    handle.force_recheck.assert_called_once()


def test_recheck_torrent_missing_handle_is_a_no_op():
    sm = _session_manager_with_mock_handles()

    sm.recheck_torrent("unknown")  # must not raise


def test_move_storage_calls_move_storage_on_the_handle():
    handle = MagicMock()
    sm = _session_manager_with_mock_handles(hash0=handle)

    sm.move_storage("hash0", "D:/new/path")

    handle.move_storage.assert_called_once_with("D:/new/path")


def test_move_storage_missing_handle_is_a_no_op():
    sm = _session_manager_with_mock_handles()

    sm.move_storage("unknown", "D:/new/path")  # must not raise


def test_on_storage_moved_updates_record_and_emits_signal():
    sm = _session_manager_with_mock_handles()
    record = TorrentRecord(info_hash="hash0", save_path="/old/path")
    sm._records["hash0"] = record

    sm._on_storage_moved("hash0", "/new/path")

    assert record.save_path == "/new/path"
    sm.storage_moved.emit.assert_called_once_with("hash0", "/new/path")


def test_on_storage_moved_unknown_hash_still_emits_signal():
    sm = _session_manager_with_mock_handles()

    sm._on_storage_moved("unknown", "/new/path")  # must not raise

    sm.storage_moved.emit.assert_called_once_with("unknown", "/new/path")


def _status_stub(info_hash: str):
    status = MagicMock()
    hashes = MagicMock()
    hashes.has_v1.return_value = True
    hashes.v1 = info_hash
    status.info_hashes = hashes
    status.name = "some.torrent"
    status.save_path = "/downloads"
    status.total_wanted = 0
    status.progress = 0.0
    status.download_rate = 0
    status.upload_rate = 0
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


def test_state_update_sets_is_private_true_once_metadata_available():
    handle = MagicMock()
    torrent_info = MagicMock()
    torrent_info.priv.return_value = True
    handle.torrent_file.return_value = torrent_info
    sm = _session_manager_with_mock_handles(hash0=handle)
    record = TorrentRecord(info_hash="hash0")
    sm._records["hash0"] = record

    sm._on_state_update([_status_stub("hash0")])

    assert record.is_private is True
    assert "hash0" in sm._private_flag_checked


def test_state_update_sets_is_private_false_and_stops_rechecking():
    handle = MagicMock()
    torrent_info = MagicMock()
    torrent_info.priv.return_value = False
    handle.torrent_file.return_value = torrent_info
    sm = _session_manager_with_mock_handles(hash0=handle)
    record = TorrentRecord(info_hash="hash0")
    sm._records["hash0"] = record

    sm._on_state_update([_status_stub("hash0")])
    assert record.is_private is False
    assert "hash0" in sm._private_flag_checked

    # A second tick must not re-query torrent_file() once already checked.
    handle.torrent_file.reset_mock()
    sm._on_state_update([_status_stub("hash0")])
    handle.torrent_file.assert_not_called()


def test_state_update_leaves_is_private_unchecked_before_metadata_arrives():
    handle = MagicMock()
    handle.torrent_file.return_value = None
    sm = _session_manager_with_mock_handles(hash0=handle)
    record = TorrentRecord(info_hash="hash0")
    sm._records["hash0"] = record

    sm._on_state_update([_status_stub("hash0")])

    assert record.is_private is False
    assert "hash0" not in sm._private_flag_checked


def test_state_update_does_not_touch_torrent_file_on_invalid_handle():
    """Regression: a state_update_alert can be dispatched for a torrent
    whose handle has already been invalidated by an async remove_torrent()
    that hasn't posted its torrent_removed_alert yet. Calling
    handle.torrent_file() on it raises RuntimeError ("invalid torrent handle
    used") in real libtorrent, which used to abort AlertDispatcher's whole
    alert batch and drop the pending torrent_removed_alert -- leaking the
    record forever. is_valid() must be checked first."""
    handle = MagicMock()
    handle.is_valid.return_value = False
    handle.torrent_file.side_effect = RuntimeError("invalid torrent handle used [libtorrent:20]")
    sm = _session_manager_with_mock_handles(hash0=handle)
    record = TorrentRecord(info_hash="hash0")
    sm._records["hash0"] = record

    sm._on_state_update([_status_stub("hash0")])  # must not raise

    handle.torrent_file.assert_not_called()
    assert record.is_private is False
    assert "hash0" not in sm._private_flag_checked
