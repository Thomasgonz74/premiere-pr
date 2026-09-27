"""Coverage for ScheduledRecheckService: periodically force-rechecks
finished torrents whose last verification is older than the configured
interval (see engine/scheduled_recheck_service.py)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.scheduled_recheck_service import ScheduledRecheckService
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class FakeSessionManager:
    def __init__(self):
        self.records = []
        self.rechecked = []

    def all_records(self):
        return list(self.records)

    def recheck_torrent(self, info_hash):
        self.rechecked.append(info_hash)


def _service(monkeypatch, enabled=True, interval_days=30):
    settings = Settings()
    settings.scheduled_recheck_enabled = enabled
    settings.scheduled_recheck_interval_days = interval_days
    session_manager = FakeSessionManager()
    service = ScheduledRecheckService(session_manager, settings)
    service._timer.stop()  # drive evaluate_now() by hand, not the real hourly timer
    return service, session_manager


def _fake_clock(monkeypatch, start=0.0):
    clock = {"now": start}

    def fake_monotonic():
        return clock["now"]

    monkeypatch.setattr("torrent2000.engine.scheduled_recheck_service.time.monotonic", fake_monotonic)
    return clock


def test_disabled_by_default_does_nothing(monkeypatch):
    service, session_manager = _service(monkeypatch, enabled=False)
    session_manager.records = [TorrentRecord(info_hash="hash1", state=TorrentState.FINISHED)]

    service.evaluate_now()

    assert session_manager.rechecked == []


def test_first_time_seen_finished_starts_the_clock_without_rechecking(monkeypatch):
    clock = _fake_clock(monkeypatch)
    service, session_manager = _service(monkeypatch)
    session_manager.records = [TorrentRecord(info_hash="hash1", state=TorrentState.FINISHED)]

    service.evaluate_now()

    assert session_manager.rechecked == []
    assert "hash1" in service._last_checked


def test_rechecks_once_the_interval_has_elapsed(monkeypatch):
    clock = _fake_clock(monkeypatch)
    service, session_manager = _service(monkeypatch, interval_days=30)
    session_manager.records = [TorrentRecord(info_hash="hash1", state=TorrentState.FINISHED)]

    service.evaluate_now()  # first sighting -- starts the clock
    assert session_manager.rechecked == []

    clock["now"] += 30 * 86400 + 1  # interval + 1 second
    service.evaluate_now()

    assert session_manager.rechecked == ["hash1"]


def test_does_not_recheck_before_the_interval_elapses(monkeypatch):
    clock = _fake_clock(monkeypatch)
    service, session_manager = _service(monkeypatch, interval_days=30)
    session_manager.records = [TorrentRecord(info_hash="hash1", state=TorrentState.FINISHED)]

    service.evaluate_now()
    clock["now"] += 10 * 86400  # well short of 30 days
    service.evaluate_now()

    assert session_manager.rechecked == []


def test_non_finished_torrents_are_ignored():
    settings = Settings()
    settings.scheduled_recheck_enabled = True
    session_manager = FakeSessionManager()
    session_manager.records = [TorrentRecord(info_hash="hash1", state=TorrentState.DOWNLOADING)]
    service = ScheduledRecheckService(session_manager, settings)
    service._timer.stop()

    service.evaluate_now()

    assert session_manager.rechecked == []
    assert service._last_checked == {}


def test_removed_torrent_bookkeeping_is_cleaned_up(monkeypatch):
    clock = _fake_clock(monkeypatch)
    service, session_manager = _service(monkeypatch)
    session_manager.records = [TorrentRecord(info_hash="hash1", state=TorrentState.FINISHED)]
    service.evaluate_now()
    assert "hash1" in service._last_checked

    session_manager.records = []  # torrent removed
    service.evaluate_now()

    assert service._last_checked == {}
