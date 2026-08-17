import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

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


def test_track_persists_across_a_fresh_service_instance():
    sm = _session_manager_with_record("abc123", uploaded=500)
    service = ShareLimitService(sm, Settings())
    service.track("abc123", time_limit_seconds=3600, data_limit_bytes=None)
    service.flush_pending_save()  # saves are debounced -- force the write now

    reloaded = ShareLimitService(sm, Settings())

    assert reloaded.is_tracked("abc123")
    limit = reloaded.limit_for("abc123")
    assert limit.time_limit_seconds == 3600
    assert limit.data_limit_bytes is None
    assert limit.uploaded_baseline == 500


def test_untrack_persists_removal():
    sm = _session_manager_with_record("abc123")
    service = ShareLimitService(sm, Settings())
    service.track("abc123", 3600, None)
    service.untrack("abc123")
    service.flush_pending_save()  # saves are debounced -- force the write now

    reloaded = ShareLimitService(sm, Settings())

    assert not reloaded.is_tracked("abc123")


def test_reached_state_persists():
    sm = _session_manager_with_record("abc123", uploaded=0)
    service = ShareLimitService(sm, Settings())
    service.track("abc123", time_limit_seconds=1, data_limit_bytes=None)
    # Simulate the limit having already been hit before the process exited.
    record = TorrentRecord(info_hash="abc123", name="x", save_path="C:\\x", all_time_uploaded=0)
    service._on_status_updated("abc123", record)
    import time

    time.sleep(1.1)
    service._on_status_updated("abc123", record)
    service.flush_pending_save()  # saves are debounced -- force the write now

    reloaded = ShareLimitService(sm, Settings())
    limit = reloaded.limit_for("abc123")
    assert limit.reached is True
    assert limit.reached_reason == "time"


def test_missing_persistence_file_starts_empty():
    sm = _session_manager_with_record("abc123")
    service = ShareLimitService(sm, Settings())
    assert service.tracked_info_hashes() == []


def test_corrupt_persistence_file_does_not_crash_startup(tmp_path):
    from torrent2000.config.paths import get_share_limits_path

    get_share_limits_path().write_text("not valid json {{{", encoding="utf-8")
    sm = _session_manager_with_record("abc123")
    service = ShareLimitService(sm, Settings())  # must not raise
    assert service.tracked_info_hashes() == []
