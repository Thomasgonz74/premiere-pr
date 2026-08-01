from dataclasses import dataclass

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.stats.leveling import LEVEL_BASE_BYTES
from torrent2000.stats.service import StatsService
from torrent2000.stats.store import StatsStore


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@dataclass
class FakeRecord:
    all_time_downloaded: int
    all_time_uploaded: int


class FakeSessionManager(QObject):
    torrent_status_updated = Signal(str, object)
    torrent_removed = Signal(str)


def test_accumulates_delta_across_status_updates(tmp_path):
    store = StatsStore(tmp_path / "stats.sqlite3")
    fake_sm = FakeSessionManager()
    service = StatsService(store, fake_sm)

    fake_sm.torrent_status_updated.emit("abc", FakeRecord(1000, 200))
    service.flush()
    total_down, total_up = store.get_totals()
    assert total_down == 1000
    assert total_up == 200

    fake_sm.torrent_status_updated.emit("abc", FakeRecord(2500, 500))
    service.flush()
    total_down, total_up = store.get_totals()
    assert total_down == 2500
    assert total_up == 500


def test_removed_torrent_flushes_final_delta_before_dropping(tmp_path):
    store = StatsStore(tmp_path / "stats.sqlite3")
    fake_sm = FakeSessionManager()
    service = StatsService(store, fake_sm)

    fake_sm.torrent_status_updated.emit("xyz", FakeRecord(500, 0))
    fake_sm.torrent_removed.emit("xyz")

    total_down, _ = store.get_totals()
    assert total_down == 500


def test_totals_survive_restart_with_fresh_handle_starting_at_zero(tmp_path):
    db_path = tmp_path / "stats.sqlite3"

    store1 = StatsStore(db_path)
    sm1 = FakeSessionManager()
    service1 = StatsService(store1, sm1)
    sm1.torrent_status_updated.emit("hash1", FakeRecord(3000, 100))
    service1.shutdown()
    store1.close()

    # Simulate app restart: new store connection, new service, but the same
    # torrent handle re-added by libtorrent starts its all_time_download back
    # at 0 -- the stored delta-tracking must not double count or lose the
    # previously accumulated total.
    store2 = StatsStore(db_path)
    total_down, total_up = store2.get_totals()
    assert total_down == 3000
    assert total_up == 100

    sm2 = FakeSessionManager()
    service2 = StatsService(store2, sm2)
    sm2.torrent_status_updated.emit("hash1", FakeRecord(0, 0))  # fresh handle
    service2.flush()
    total_down, total_up = store2.get_totals()
    assert total_down == 3000  # unchanged, delta was clamped at 0 not negative
    assert total_up == 100


def test_level_reflects_combined_download_and_upload(tmp_path):
    store = StatsStore(tmp_path / "stats.sqlite3")
    fake_sm = FakeSessionManager()
    service = StatsService(store, fake_sm)

    fake_sm.torrent_status_updated.emit("abc", FakeRecord(LEVEL_BASE_BYTES // 2, LEVEL_BASE_BYTES // 2))
    service.flush()
    snap = service.current_snapshot()
    assert snap.level == 1
