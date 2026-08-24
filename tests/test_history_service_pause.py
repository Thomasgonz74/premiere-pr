"""Minimal coverage for HistoryService's set_paused/_paused guard (added for
MemoryPressureGovernor, see engine/memory_pressure_governor.py). Follows
tests/test_history_service.py's fixture/fake pattern.
"""

from dataclasses import dataclass

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.history_store import HistoryStore


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@dataclass
class FakeRecord:
    info_hash: str = "abc"
    name: str = "Example.Torrent"
    total_size: int = 1000
    all_time_downloaded: int = 500
    all_time_uploaded: int = 250


class FakeSessionManager(QObject):
    torrent_status_updated = Signal(str, object)
    torrent_removed = Signal(str)


def test_paused_service_does_not_log_removed_torrent(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    fake_sm = FakeSessionManager()
    service = HistoryService(store, fake_sm)
    service.set_paused(True)

    fake_sm.torrent_status_updated.emit("abc", FakeRecord())
    fake_sm.torrent_removed.emit("abc")

    assert service.all_entries() == []


def test_paused_service_still_drops_last_known_record_to_avoid_leak(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    fake_sm = FakeSessionManager()
    service = HistoryService(store, fake_sm)
    service.set_paused(True)

    fake_sm.torrent_status_updated.emit("abc", FakeRecord())
    fake_sm.torrent_removed.emit("abc")

    assert "abc" not in service._last_known


def test_unpausing_resumes_normal_logging(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    fake_sm = FakeSessionManager()
    service = HistoryService(store, fake_sm)
    service.set_paused(True)
    service.set_paused(False)

    fake_sm.torrent_status_updated.emit("abc", FakeRecord())
    fake_sm.torrent_removed.emit("abc")

    entries = service.all_entries()
    assert len(entries) == 1
    assert entries[0].info_hash == "abc"
