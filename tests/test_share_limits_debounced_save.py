import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_share_limits_path
from torrent2000.config.settings import Settings
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.torrent_item import TorrentRecord


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _session_manager_with_record(info_hash: str, uploaded: int = 0) -> MagicMock:
    sm = MagicMock()
    sm.get_record.return_value = TorrentRecord(info_hash=info_hash, name="x", save_path="C:\\x", all_time_uploaded=uploaded)
    return sm


def test_rapid_track_calls_coalesce_into_a_single_disk_write():
    """Two track() calls before the debounce window elapses must still only
    hit disk once, and that one write must reflect the latest state."""
    sm = _session_manager_with_record("abc123")
    service = ShareLimitService(sm, Settings())

    calls = []
    original_save = service._save
    # Re-point the timer's timeout at a counting wrapper so we can assert on
    # how many times the real disk-writing body actually ran, without
    # sleeping in real time -- we fire the timeout ourselves below.
    service._save_timer.timeout.disconnect()
    service._save_timer.timeout.connect(lambda: (calls.append(1), original_save()))

    service.track("abc123", time_limit_seconds=3600, data_limit_bytes=None)
    service.track("abc123", time_limit_seconds=7200, data_limit_bytes=1024)

    assert calls == []  # still within the debounce window -- nothing written yet
    assert service._save_timer.isActive()

    service._save_timer.timeout.emit()

    assert calls == [1]
    on_disk = json.loads(get_share_limits_path().read_text(encoding="utf-8"))
    assert on_disk["abc123"]["time_limit_seconds"] == 7200
    assert on_disk["abc123"]["data_limit_bytes"] == 1024


def test_schedule_save_restarts_the_debounce_window_instead_of_stacking():
    sm = _session_manager_with_record("abc123")
    service = ShareLimitService(sm, Settings())

    service.track("abc123", time_limit_seconds=1, data_limit_bytes=None)
    assert service._save_timer.isActive()
    service.track("abc123", time_limit_seconds=2, data_limit_bytes=None)

    # A second call before the first fires restarts (not stacks) the timer --
    # still exactly one pending, active single-shot timer.
    assert service._save_timer.isActive()
    assert service._save_timer.remainingTime() <= service._SAVE_DEBOUNCE_MS

    service.flush_pending_save()
    assert not service._save_timer.isActive()


def test_track_then_untrack_in_quick_succession_persists_final_state_only():
    sm = _session_manager_with_record("abc123")
    service = ShareLimitService(sm, Settings())

    service.track("abc123", time_limit_seconds=3600, data_limit_bytes=None)
    service.untrack("abc123")
    service.flush_pending_save()

    on_disk = json.loads(get_share_limits_path().read_text(encoding="utf-8"))
    assert on_disk == {}

    reloaded = ShareLimitService(sm, Settings())
    assert not reloaded.is_tracked("abc123")


def test_flush_pending_save_is_a_noop_when_nothing_is_pending():
    sm = _session_manager_with_record("abc123")
    service = ShareLimitService(sm, Settings())

    with patch.object(service, "_save") as save_mock:
        service.flush_pending_save()

    save_mock.assert_not_called()


def test_flush_pending_save_forces_immediate_write_of_a_pending_change():
    sm = _session_manager_with_record("abc123", uploaded=500)
    service = ShareLimitService(sm, Settings())

    service.track("abc123", time_limit_seconds=3600, data_limit_bytes=None)
    assert service._save_timer.isActive()
    assert not get_share_limits_path().exists()

    service.flush_pending_save()

    assert not service._save_timer.isActive()
    on_disk = json.loads(get_share_limits_path().read_text(encoding="utf-8"))
    assert on_disk["abc123"]["time_limit_seconds"] == 3600
    assert on_disk["abc123"]["uploaded_baseline"] == 500

    reloaded = ShareLimitService(sm, Settings())
    assert reloaded.is_tracked("abc123")
    assert reloaded.limit_for("abc123").time_limit_seconds == 3600
