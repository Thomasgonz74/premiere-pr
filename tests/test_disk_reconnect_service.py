"""Coverage for DiskReconnectService: opt-in (Settings.auto_resume_on_disk_
reconnect, off by default), matches the reconnected drive by volume serial
number (not save_path/drive letter alone), and only resumes torrents it is
actually tracking as file-error-paused. Mirrors test_battery_pause_service.py's
structure -- a FakeSessionManager with real Qt signals plus plain Python
bookkeeping, and get_volume_serial monkeypatched module-wide since real
volume identity isn't what this test is exercising."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import disk_reconnect_service as drs_module
from torrent2000.engine.disk_reconnect_service import DiskReconnectService


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class FakeRecord:
    def __init__(self, info_hash: str, save_path: str) -> None:
        self.info_hash = info_hash
        self.save_path = save_path


class FakeSessionManager(QObject):
    file_error = Signal(str, str)
    torrent_removed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.records: dict[str, FakeRecord] = {}
        self.resumed: list[str] = []

    def get_record(self, info_hash: str):
        return self.records.get(info_hash)

    def all_records(self):
        return list(self.records.values())

    def resume_torrent(self, info_hash: str) -> None:
        self.resumed.append(info_hash)


def _settings(enabled: bool) -> Settings:
    settings = Settings()
    settings.auto_resume_on_disk_reconnect = enabled
    return settings


def test_disabled_by_default_never_resumes(monkeypatch):
    monkeypatch.setattr(drs_module, "get_volume_serial", lambda path: 111)
    fake_sm = FakeSessionManager()
    fake_sm.records["h0"] = FakeRecord("h0", "E:/downloads")
    service = DiskReconnectService(fake_sm, _settings(enabled=False))

    fake_sm.file_error.emit("h0", "the device is not ready")
    service.check_now()

    assert fake_sm.resumed == []


def test_resumes_when_the_volume_serial_matches_after_reconnect(monkeypatch):
    fake_sm = FakeSessionManager()
    fake_sm.records["h0"] = FakeRecord("h0", "E:/downloads")
    service = DiskReconnectService(fake_sm, _settings(enabled=True))

    # Healthy tick: caches the drive's serial while it's still reachable.
    monkeypatch.setattr(drs_module, "get_volume_serial", lambda path: 111)
    service.check_now()

    # Disconnected -- file_error fires, torrent tracked as pending.
    fake_sm.file_error.emit("h0", "the device is not ready")
    assert fake_sm.resumed == []

    # Still gone.
    monkeypatch.setattr(drs_module, "get_volume_serial", lambda path: None)
    service.check_now()
    assert fake_sm.resumed == []

    # Reconnected, same serial -> auto-resume.
    monkeypatch.setattr(drs_module, "get_volume_serial", lambda path: 111)
    service.check_now()
    assert fake_sm.resumed == ["h0"]


def test_does_not_resume_when_a_different_drive_reuses_the_same_letter(monkeypatch):
    fake_sm = FakeSessionManager()
    fake_sm.records["h0"] = FakeRecord("h0", "E:/downloads")
    service = DiskReconnectService(fake_sm, _settings(enabled=True))

    monkeypatch.setattr(drs_module, "get_volume_serial", lambda path: 111)
    service.check_now()
    fake_sm.file_error.emit("h0", "the device is not ready")

    # A different drive now sits at the same letter.
    monkeypatch.setattr(drs_module, "get_volume_serial", lambda path: 222)
    service.check_now()

    assert fake_sm.resumed == []


def test_removed_torrent_is_dropped_from_pending(monkeypatch):
    monkeypatch.setattr(drs_module, "get_volume_serial", lambda path: 111)
    fake_sm = FakeSessionManager()
    fake_sm.records["h0"] = FakeRecord("h0", "E:/downloads")
    service = DiskReconnectService(fake_sm, _settings(enabled=True))
    service.check_now()
    fake_sm.file_error.emit("h0", "the device is not ready")

    fake_sm.torrent_removed.emit("h0")
    service.check_now()

    assert fake_sm.resumed == []
    assert "h0" not in service._pending


def test_unresolvable_serial_at_pause_time_never_auto_resumes(monkeypatch):
    """If the drive was already gone the very first time this service ever
    saw the torrent's save_path (no cached last-known-good serial), there is
    nothing to compare a reconnect against -- it must not just resume the
    moment *any* drive answers at that path."""
    monkeypatch.setattr(drs_module, "get_volume_serial", lambda path: None)
    fake_sm = FakeSessionManager()
    fake_sm.records["h0"] = FakeRecord("h0", "E:/downloads")
    service = DiskReconnectService(fake_sm, _settings(enabled=True))

    fake_sm.file_error.emit("h0", "the device is not ready")

    monkeypatch.setattr(drs_module, "get_volume_serial", lambda path: 111)
    service.check_now()

    assert fake_sm.resumed == []
