"""Minimal coverage for the decision journal: DecisionJournalService wires up
to the three signals that actually exist today (SessionManager.file_error,
KnownDiskService.diskConfirmationRequested, DiskSpaceMonitor.low_space_warning),
appends a French, human-readable JSONL line per event, and read_recent_entries
returns them most-recent-first. Mirrors test_settings_history.py's
isolated_data_dir + JSONL-roundtrip structure and
test_notifications_file_error.py's FakeSessionManager/FakeRecord pattern for
faking cross-object Qt signals."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.engine.decision_journal import DecisionJournalService, read_recent_entries


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class FakeRecord:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeSessionManager(QObject):
    file_error = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.records: dict[str, FakeRecord] = {}

    def get_record(self, info_hash: str):
        return self.records.get(info_hash)


class FakeKnownDiskService(QObject):
    diskConfirmationRequested = Signal(str, str)


class FakeDiskSpaceMonitor(QObject):
    low_space_warning = Signal(str, str)


def _wired_service():
    session_manager = FakeSessionManager()
    known_disk_service = FakeKnownDiskService()
    disk_space_monitor = FakeDiskSpaceMonitor()
    service = DecisionJournalService(session_manager, known_disk_service, disk_space_monitor)
    return service, session_manager, known_disk_service, disk_space_monitor


def test_read_recent_entries_empty_when_no_file_exists():
    assert read_recent_entries() == []


def test_file_error_journals_the_torrent_name():
    _service, session_manager, _kds, _dsm = _wired_service()
    session_manager.records["abc123"] = FakeRecord("Example.Torrent")

    session_manager.file_error.emit("abc123", "the device is not ready")

    entries = read_recent_entries()
    assert len(entries) == 1
    assert "Example.Torrent" in entries[0]["text"]
    assert "the device is not ready" in entries[0]["text"]
    assert entries[0]["timestamp"]


def test_file_error_falls_back_to_the_hash_when_the_record_is_unknown():
    _service, session_manager, _kds, _dsm = _wired_service()

    session_manager.file_error.emit("deadbeef0000", "boom")

    entries = read_recent_entries()
    assert "deadbeef0000" in entries[0]["text"]


def test_disk_confirmation_requested_journals_label_and_action():
    _service, _sm, known_disk_service, _dsm = _wired_service()

    known_disk_service.diskConfirmationRequested.emit(
        '{"label": "BACKUP_USB", "mountpoint": "E:\\\\"}', "copy to D:/Backups"
    )

    entries = read_recent_entries()
    assert "BACKUP_USB" in entries[0]["text"]
    assert "copy to D:/Backups" in entries[0]["text"]


def test_low_space_warning_journals_the_save_path():
    _service, _sm, _kds, disk_space_monitor = _wired_service()

    disk_space_monitor.low_space_warning.emit("C:/downloads", "some message")

    entries = read_recent_entries()
    assert "C:/downloads" in entries[0]["text"]


def test_entries_are_returned_most_recent_first():
    service, session_manager, _kds, _dsm = _wired_service()
    session_manager.records["hash1"] = FakeRecord("First")
    session_manager.records["hash2"] = FakeRecord("Second")

    session_manager.file_error.emit("hash1", "err1")
    session_manager.file_error.emit("hash2", "err2")

    entries = read_recent_entries()
    assert len(entries) == 2
    assert "Second" in entries[0]["text"]
    assert "First" in entries[1]["text"]

    # recent_entries() is the same read, exposed as a static method for the
    # bridge to call without importing the module function directly.
    assert service.recent_entries(1) == [entries[0]]
