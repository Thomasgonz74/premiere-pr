"""Regression guard for the "restored torrents lose all progress" bug.

handle.save_resume_data() without lt.torrent_handle.save_info_dict writes a
.fastresume with ti=None -- on the next launch, libtorrent silently
re-fetches metadata and re-hashes everything from scratch instead of doing a
real fast-resume. Both save call sites (shutdown, and the periodic autosave)
must pass that flag.
"""

from unittest.mock import MagicMock

import libtorrent as lt

from torrent2000.engine.session_manager import SessionManager


def _session_manager_with_mock_handles(*handles):
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    sm._timer = MagicMock()
    sm._resume_save_timer = MagicMock()
    sm._session = MagicMock()
    sm._handles = {f"hash{i}": h for i, h in enumerate(handles)}
    return sm


def test_shutdown_passes_save_info_dict_flag():
    handle = MagicMock()
    handle.is_valid.return_value = True
    sm = _session_manager_with_mock_handles(handle)
    sm._session.pop_alerts.return_value = []  # nothing pending to drain

    sm.shutdown(timeout_ms=0)

    handle.save_resume_data.assert_called_once_with(lt.torrent_handle.save_info_dict)


def test_periodic_autosave_passes_save_info_dict_and_only_if_modified():
    handle = MagicMock()
    handle.is_valid.return_value = True
    sm = _session_manager_with_mock_handles(handle)

    sm._save_all_resume_data()

    expected_flags = lt.torrent_handle.save_info_dict | lt.torrent_handle.only_if_modified
    handle.save_resume_data.assert_called_once_with(expected_flags)


def test_shutdown_stops_the_periodic_autosave_timer():
    handle = MagicMock()
    handle.is_valid.return_value = True
    sm = _session_manager_with_mock_handles(handle)
    sm._session.pop_alerts.return_value = []

    sm.shutdown(timeout_ms=0)

    sm._resume_save_timer.stop.assert_called_once()


def test_invalid_handles_are_skipped_without_saving():
    handle = MagicMock()
    handle.is_valid.return_value = False
    sm = _session_manager_with_mock_handles(handle)

    sm._save_all_resume_data()

    handle.save_resume_data.assert_not_called()
