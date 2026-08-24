"""Minimal coverage for the deadline-based queue priority feature: TorrentRecord.deadline,
SessionManager.set_deadline, and the SessionManager._apply_deadline_priorities sweep that
_on_tick calls every 300ms (throttled internally to _DEADLINE_SWEEP_INTERVAL_S)."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

from torrent2000.engine.session_manager import DEADLINE_URGENT_WINDOW_S, SessionManager
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState

_NOW = 1_000_000.0


def _session_manager_with_mock_handles(**handles):
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    sm._handles = dict(handles)
    sm._records = {}
    sm._last_deadline_sweep = 0.0  # never swept yet -- throttle won't block the first call
    return sm


def _downloading_record(info_hash: str, deadline) -> TorrentRecord:
    return TorrentRecord(info_hash=info_hash, state=TorrentState.DOWNLOADING, deadline=deadline)


# --------------------------------------------------------------------- set_deadline


def test_set_deadline_sets_the_timestamp():
    sm = _session_manager_with_mock_handles()
    sm._records["hash0"] = TorrentRecord(info_hash="hash0")

    sm.set_deadline("hash0", 12345.0)

    assert sm._records["hash0"].deadline == 12345.0


def test_set_deadline_none_clears_it():
    sm = _session_manager_with_mock_handles()
    sm._records["hash0"] = TorrentRecord(info_hash="hash0", deadline=12345.0)

    sm.set_deadline("hash0", None)

    assert sm._records["hash0"].deadline is None


def test_set_deadline_unknown_hash_is_a_noop():
    sm = _session_manager_with_mock_handles()

    sm.set_deadline("unknown", 12345.0)  # must not raise


# --------------------------------------------------------------- deadline priority sweep


def test_no_deadline_is_never_bumped(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: _NOW)
    handle = MagicMock()
    sm = _session_manager_with_mock_handles(hash0=handle)
    sm._records["hash0"] = _downloading_record("hash0", deadline=None)

    sm._apply_deadline_priorities()

    handle.queue_position_up.assert_not_called()


def test_deadline_far_in_the_future_is_not_bumped_yet(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: _NOW)
    handle = MagicMock()
    sm = _session_manager_with_mock_handles(hash0=handle)
    sm._records["hash0"] = _downloading_record("hash0", deadline=_NOW + DEADLINE_URGENT_WINDOW_S + 60)

    sm._apply_deadline_priorities()

    handle.queue_position_up.assert_not_called()


def test_deadline_inside_the_urgent_window_is_bumped(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: _NOW)
    handle = MagicMock()
    sm = _session_manager_with_mock_handles(hash0=handle)
    sm._records["hash0"] = _downloading_record("hash0", deadline=_NOW + 3600)  # 1h out

    sm._apply_deadline_priorities()

    assert handle.queue_position_up.call_count >= 1


def test_overdue_deadline_gets_max_urgency_bump(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: _NOW)
    handle = MagicMock()
    sm = _session_manager_with_mock_handles(hash0=handle)
    sm._records["hash0"] = _downloading_record("hash0", deadline=_NOW - 999)  # already passed

    sm._apply_deadline_priorities()

    assert handle.queue_position_up.call_count == 5  # clamped urgency=1.0 -> 1 + round(1.0*4)


def test_closer_deadline_is_bumped_more_than_a_farther_one(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: _NOW)
    near_handle = MagicMock()
    far_handle = MagicMock()
    sm = _session_manager_with_mock_handles(near=near_handle, far=far_handle)
    sm._records["near"] = _downloading_record("near", deadline=_NOW + 600)  # 10 min out
    sm._records["far"] = _downloading_record("far", deadline=_NOW + 23 * 3600)  # 23h out

    sm._apply_deadline_priorities()

    assert near_handle.queue_position_up.call_count > far_handle.queue_position_up.call_count


def test_non_active_state_is_not_bumped_even_with_an_urgent_deadline(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: _NOW)
    handle = MagicMock()
    sm = _session_manager_with_mock_handles(hash0=handle)
    record = _downloading_record("hash0", deadline=_NOW + 60)
    record.state = TorrentState.SEEDING  # already finished/seeding -- no queue to bump
    sm._records["hash0"] = record

    sm._apply_deadline_priorities()

    handle.queue_position_up.assert_not_called()


def test_sweep_is_throttled_and_does_not_rerun_immediately(monkeypatch):
    fake_now = [_NOW]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])
    handle = MagicMock()
    sm = _session_manager_with_mock_handles(hash0=handle)
    sm._records["hash0"] = _downloading_record("hash0", deadline=_NOW + 60)

    sm._apply_deadline_priorities()
    first_call_count = handle.queue_position_up.call_count
    assert first_call_count >= 1

    fake_now[0] += 1  # 1s later -- still inside _DEADLINE_SWEEP_INTERVAL_S (10s)
    sm._apply_deadline_priorities()

    assert handle.queue_position_up.call_count == first_call_count  # no extra bump yet
