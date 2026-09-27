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

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_decision_journal_path
from torrent2000.engine import decision_journal
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
    torrent_removed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.records: dict[str, FakeRecord] = {}

    def get_record(self, info_hash: str):
        return self.records.get(info_hash)


class FakeKnownDiskService(QObject):
    diskConfirmationRequested = Signal(str, str)


class FakeDiskSpaceMonitor(QObject):
    low_space_warning = Signal(str, str)


class FakeShareLimitService(QObject):
    limit_reached = Signal(str, str)


class FakeAutoShutdownService(QObject):
    shutdown_countdown_started = Signal(int)


class FakeRssFeedService(QObject):
    items_found = Signal(str, list)


def _wired_service():
    session_manager = FakeSessionManager()
    known_disk_service = FakeKnownDiskService()
    disk_space_monitor = FakeDiskSpaceMonitor()
    service = DecisionJournalService(session_manager, known_disk_service, disk_space_monitor)
    return service, session_manager, known_disk_service, disk_space_monitor


def _fully_wired_service():
    session_manager = FakeSessionManager()
    known_disk_service = FakeKnownDiskService()
    disk_space_monitor = FakeDiskSpaceMonitor()
    share_limit_service = FakeShareLimitService()
    auto_shutdown_service = FakeAutoShutdownService()
    rss_feed_service = FakeRssFeedService()
    service = DecisionJournalService(
        session_manager,
        known_disk_service,
        disk_space_monitor,
        share_limit_service=share_limit_service,
        auto_shutdown_service=auto_shutdown_service,
        rss_feed_service=rss_feed_service,
    )
    # `service` itself must be kept alive by the caller -- with no parent and
    # no Python reference held here, it would be garbage-collected (and its
    # Qt connections silently dropped) the moment this function returns.
    return session_manager, share_limit_service, auto_shutdown_service, rss_feed_service, service


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


def test_optional_services_default_to_none_without_raising():
    # The three new params are optional so existing callers/tests (like
    # _wired_service above) that only cover the original three signals keep
    # working unchanged.
    _wired_service()


def test_limit_reached_journals_the_torrent_name_and_reason():
    session_manager, share_limit_service, _asd, _rfs, _svc = _fully_wired_service()
    session_manager.records["abc123"] = FakeRecord("Example.Torrent")

    share_limit_service.limit_reached.emit("abc123", "ratio")

    entries = read_recent_entries()
    assert "Example.Torrent" in entries[0]["text"]
    assert "ratio" in entries[0]["text"]


def test_shutdown_countdown_started_journals_the_delay():
    _sm, _sls, auto_shutdown_service, _rfs, _svc = _fully_wired_service()

    auto_shutdown_service.shutdown_countdown_started.emit(60)

    entries = read_recent_entries()
    assert "60" in entries[0]["text"]


def test_rss_items_found_journals_titles_and_redacts_the_feed_url():
    _sm, _sls, _asd, rss_feed_service, _svc = _fully_wired_service()

    rss_feed_service.items_found.emit(
        "https://tracker.example/rss?passkey=SECRET123", [{"title": "Ubuntu.24.04", "guid": "g1"}]
    )

    entries = read_recent_entries()
    assert "Ubuntu.24.04" in entries[0]["text"]
    assert "SECRET123" not in entries[0]["text"]
    assert "tracker.example/rss" in entries[0]["text"]


def test_repeated_file_errors_for_one_torrent_are_journaled_once_until_removed():
    """A burst of file errors (100 froze the GUI ~1.2-1.5 s) must not write
    one line each -- one per torrent, like ui/notifications.py, reset on removal."""
    _service, session_manager, _kds, _dsm = _wired_service()

    for _ in range(5):
        session_manager.file_error.emit("abc123", "the device is not ready")
    session_manager.file_error.emit("def456", "other torrent")
    assert len(read_recent_entries()) == 2

    session_manager.torrent_removed.emit("abc123")
    session_manager.file_error.emit("abc123", "re-added, failing again")
    assert len(read_recent_entries()) == 3


def test_append_does_not_reread_the_journal_below_the_threshold_and_trims_to_200_lines(monkeypatch):
    """Re-reading the freshly written file after every append triggered a
    Defender scan (11-15 ms per entry): the size comes from f.tell(), and a
    trim, once due, always goes back to exactly the last 200 lines."""
    reads = []
    real_read_text = Path.read_text
    monkeypatch.setattr(
        Path, "read_text", lambda self, *a, **k: (reads.append(self), real_read_text(self, *a, **k))[1]
    )

    for i in range(250):
        decision_journal._append(f"entry {i}")
    assert reads == []  # 250 short lines stay under the threshold -- never re-read
    assert len(real_read_text(get_decision_journal_path(), encoding="utf-8").splitlines()) == 250

    monkeypatch.setattr(decision_journal, "_TRIM_THRESHOLD_BYTES", 0)
    decision_journal._append("entry 250")

    lines = real_read_text(get_decision_journal_path(), encoding="utf-8").splitlines()
    assert len(lines) == 200
    assert "entry 250" in lines[-1] and "entry 51" in lines[0]
    assert list(get_decision_journal_path().parent.glob("*.tmp")) == []  # replaced atomically
