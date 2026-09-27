"""Regression guard for the "restored torrents lose all progress" bug.

handle.save_resume_data() without lt.torrent_handle.save_info_dict writes a
.fastresume with ti=None -- on the next launch, libtorrent silently
re-fetches metadata and re-hashes everything from scratch instead of doing a
real fast-resume. Both save call sites (shutdown, and the periodic autosave)
must pass that flag.
"""

import collections
from unittest.mock import MagicMock, patch

import libtorrent as lt

from torrent2000.engine.session_manager import _RESUME_SAVES_PER_TICK, SessionManager


def _session_manager_with_mock_handles(*handles):
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    sm._timer = MagicMock()
    sm._resume_save_timer = MagicMock()
    sm._session = MagicMock()
    sm._handles = {f"hash{i}": h for i, h in enumerate(handles)}
    sm._resume_save_queue = collections.deque()
    return sm


def _save_alert_for(handle, info_hash):
    handle.info_hashes.return_value.has_v1.return_value = True
    handle.info_hashes.return_value.v1 = info_hash
    alert = MagicMock(spec=lt.save_resume_data_alert)
    alert.handle = handle
    alert.params = MagicMock()
    return alert


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
    sm._drain_resume_save_queue()

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
    sm._drain_resume_save_queue()

    handle.save_resume_data.assert_not_called()


def test_periodic_autosave_is_spread_over_ticks_instead_of_one_burst():
    """The 2-minute timer only queues the saves; each tick posts at most
    _RESUME_SAVES_PER_TICK of them, so N resume writes never land in a
    single pop_alerts() burst on the GUI thread. A refill while the queue is
    still draining doesn't queue anything twice, and a torrent removed after
    being queued is skipped at pop time."""
    handles = [MagicMock() for _ in range(5)]
    for handle in handles:
        handle.is_valid.return_value = True
    sm = _session_manager_with_mock_handles(*handles)

    sm._save_all_resume_data()
    assert sum(h.save_resume_data.call_count for h in handles) == 0

    sm._drain_resume_save_queue()
    assert sum(h.save_resume_data.call_count for h in handles) == _RESUME_SAVES_PER_TICK

    sm._save_all_resume_data()  # timer fires again mid-drain
    del sm._handles["hash4"]  # removed while still queued
    while sm._resume_save_queue:
        sm._drain_resume_save_queue()

    # hash0/hash1 were saved before the refill, so they're queued again for
    # the second round; hash2/hash3 were still queued, so only once.
    assert [h.save_resume_data.call_count for h in handles] == [2, 2, 1, 1, 0]


def test_shutdown_pumps_qt_events_while_waiting_for_pending_resume_data():
    """shutdown()'s wait loop runs on the GUI thread; it must call
    QCoreApplication.processEvents() each iteration so Qt keeps pumping
    window messages (otherwise Windows marks the process "Not Responding"
    and the window ghosts/whites-out) while the actual wait-for-alerts /
    save logic is unaffected."""
    handle = MagicMock()
    handle.is_valid.return_value = True
    sm = _session_manager_with_mock_handles(handle)

    alert = _save_alert_for(handle, "hash0")

    # First two polls find nothing pending yet; the third delivers the
    # resume-data alert that satisfies the single pending save.
    sm._session.pop_alerts.side_effect = [[], [], [alert]]

    with (
        patch("torrent2000.engine.session_manager.QCoreApplication") as mock_qapp,
        patch("torrent2000.engine.session_manager.persistence.save_resume_params") as mock_save,
        patch("time.sleep"),
    ):
        sm.shutdown(timeout_ms=3000)

    assert mock_qapp.processEvents.call_count == 3
    mock_save.assert_called_once_with("hash0", alert.params)


def test_shutdown_does_not_pump_qt_events_when_nothing_is_pending():
    """No pending saves means the wait loop body (and therefore
    processEvents) never runs at all -- unchanged from before this fix."""
    handle = MagicMock()
    handle.is_valid.return_value = False  # no valid handles -> pending stays 0
    sm = _session_manager_with_mock_handles(handle)

    with patch("torrent2000.engine.session_manager.QCoreApplication") as mock_qapp:
        sm.shutdown(timeout_ms=3000)

    mock_qapp.processEvents.assert_not_called()
    sm._session.pop_alerts.assert_not_called()


def test_shutdown_waits_for_each_torrents_own_final_save():
    """The last tick may have left _RESUME_SAVES_PER_TICK periodic saves in
    flight; their alerts answer first and must not stand in for the final
    save of other torrents -- counting alerts would stop the wait before
    hash2's arrives, leaving its older .fastresume on disk."""
    handles = [MagicMock() for _ in range(3)]
    for handle in handles:
        handle.is_valid.return_value = True
    sm = _session_manager_with_mock_handles(*handles)
    alerts = [_save_alert_for(handle, f"hash{i}") for i, handle in enumerate(handles)]
    sm._session.pop_alerts.side_effect = [
        [alerts[0], alerts[1]],  # the two periodic saves still in flight
        [alerts[0], alerts[1]],  # shutdown's own, in request order
        [alerts[2]],
    ]

    with (
        patch("torrent2000.engine.session_manager.QCoreApplication"),
        patch("torrent2000.engine.session_manager.persistence.save_resume_params") as mock_save,
        patch("time.sleep"),
    ):
        sm.shutdown(timeout_ms=3000)

    assert [call.args[0] for call in mock_save.call_args_list] == ["hash0", "hash1", "hash0", "hash1", "hash2"]
