from dataclasses import dataclass

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import disk_space_monitor as dsm_module
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor
from torrent2000.engine.torrent_item import TorrentState


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@dataclass
class FakeRecord:
    save_path: str
    state: TorrentState = TorrentState.DOWNLOADING


class FakeSessionManager(QObject):
    def __init__(self):
        super().__init__()
        self.records: list = []

    def all_records(self):
        return list(self.records)


class FakeUsage:
    def __init__(self, free_mb: float):
        self.free = int(free_mb * 1024 * 1024)


def _settings(threshold_mb: int = 1024, enabled: bool = True) -> Settings:
    settings = Settings()
    settings.disk_space_warning_enabled = enabled
    settings.disk_space_warning_threshold_mb = threshold_mb
    return settings


def test_disabled_monitor_never_warns(monkeypatch):
    monkeypatch.setattr(dsm_module.shutil, "disk_usage", lambda path: FakeUsage(1))
    settings = _settings(enabled=False)
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(save_path="C:/downloads")]
    monitor = DiskSpaceMonitor(fake_sm, settings)

    warnings = []
    monitor.low_space_warning.connect(lambda path, msg: warnings.append((path, msg)))
    monitor.check_now()

    assert warnings == []


def test_warns_once_when_below_threshold(monkeypatch):
    monkeypatch.setattr(dsm_module.shutil, "disk_usage", lambda path: FakeUsage(100))
    settings = _settings(threshold_mb=500)
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(save_path="C:/downloads")]
    monitor = DiskSpaceMonitor(fake_sm, settings)

    warnings = []
    monitor.low_space_warning.connect(lambda path, msg: warnings.append((path, msg)))
    monitor.check_now()
    monitor.check_now()  # still below threshold -- must not warn a second time

    assert len(warnings) == 1
    assert warnings[0][0] == "C:/downloads"


def test_ignores_torrents_that_are_not_actively_downloading(monkeypatch):
    monkeypatch.setattr(dsm_module.shutil, "disk_usage", lambda path: FakeUsage(1))
    settings = _settings(threshold_mb=500)
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(save_path="C:/downloads", state=TorrentState.PAUSED)]
    monitor = DiskSpaceMonitor(fake_sm, settings)

    warnings = []
    monitor.low_space_warning.connect(lambda path, msg: warnings.append((path, msg)))
    monitor.check_now()

    assert warnings == []


def test_rewarns_after_recovering_above_threshold(monkeypatch):
    settings = _settings(threshold_mb=500)
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(save_path="C:/downloads")]
    monitor = DiskSpaceMonitor(fake_sm, settings)

    warnings = []
    monitor.low_space_warning.connect(lambda path, msg: warnings.append((path, msg)))

    monkeypatch.setattr(dsm_module.shutil, "disk_usage", lambda path: FakeUsage(100))
    monitor.check_now()  # below threshold -> warns
    monkeypatch.setattr(dsm_module.shutil, "disk_usage", lambda path: FakeUsage(900))
    monitor.check_now()  # recovered -> no new warning, but resets the episode
    monkeypatch.setattr(dsm_module.shutil, "disk_usage", lambda path: FakeUsage(100))
    monitor.check_now()  # below again -> warns a second time

    assert len(warnings) == 2
