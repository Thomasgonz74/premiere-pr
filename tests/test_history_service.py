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


def test_removed_torrent_is_logged_with_last_known_stats(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    fake_sm = FakeSessionManager()
    service = HistoryService(store, fake_sm)

    fake_sm.torrent_status_updated.emit("abc", FakeRecord())
    fake_sm.torrent_removed.emit("abc")

    entries = service.all_entries()
    assert len(entries) == 1
    assert entries[0].name == "Example.Torrent"
    assert entries[0].total_downloaded == 500
    assert entries[0].total_uploaded == 250
    assert entries[0].event == "removed"


def test_removal_without_prior_status_update_is_not_logged(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    fake_sm = FakeSessionManager()
    service = HistoryService(store, fake_sm)

    fake_sm.torrent_removed.emit("never-seen")

    assert service.all_entries() == []


def test_entry_added_signal_fires_on_removal(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    fake_sm = FakeSessionManager()
    service = HistoryService(store, fake_sm)

    fired = []
    service.entry_added.connect(lambda: fired.append(True))

    fake_sm.torrent_status_updated.emit("abc", FakeRecord())
    fake_sm.torrent_removed.emit("abc")

    assert fired == [True]


def test_history_persists_across_store_reopen(tmp_path):
    db_path = tmp_path / "history.sqlite3"

    store1 = HistoryStore(db_path)
    fake_sm = FakeSessionManager()
    service1 = HistoryService(store1, fake_sm)
    fake_sm.torrent_status_updated.emit("abc", FakeRecord())
    fake_sm.torrent_removed.emit("abc")
    store1.close()

    store2 = HistoryStore(db_path)
    entries = store2.all_entries()
    assert len(entries) == 1
    assert entries[0].name == "Example.Torrent"


def test_all_entries_respects_limit(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    fake_sm = FakeSessionManager()
    service = HistoryService(store, fake_sm)

    for i in range(5):
        fake_sm.torrent_status_updated.emit(f"hash{i}", FakeRecord(info_hash=f"hash{i}", name=f"Torrent{i}"))
        fake_sm.torrent_removed.emit(f"hash{i}")

    assert len(service.all_entries(limit=3)) == 3
    # Most recent first.
    assert service.all_entries(limit=1)[0].name == "Torrent4"
