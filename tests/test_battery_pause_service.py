from dataclasses import dataclass

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import battery_pause_service as bps_module
from torrent2000.engine.battery_pause_service import BatteryPauseService
from torrent2000.engine.torrent_item import TorrentState


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@dataclass
class FakeRecord:
    info_hash: str
    state: TorrentState = TorrentState.DOWNLOADING


@dataclass
class FakeBattery:
    power_plugged: bool


class FakeSessionManager(QObject):
    def __init__(self):
        super().__init__()
        self.records: list = []
        self.paused: list[str] = []
        self.resumed: list[str] = []

    def all_records(self):
        return list(self.records)

    def pause_torrent(self, info_hash: str) -> None:
        self.paused.append(info_hash)

    def resume_torrent(self, info_hash: str) -> None:
        self.resumed.append(info_hash)


def _settings(enabled: bool = True) -> Settings:
    settings = Settings()
    settings.pause_on_battery_enabled = enabled
    return settings


def test_disabled_by_default_does_nothing_on_battery(monkeypatch):
    monkeypatch.setattr(bps_module.psutil, "sensors_battery", lambda: FakeBattery(power_plugged=False))
    settings = _settings(enabled=False)
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(info_hash="abc")]
    service = BatteryPauseService(fake_sm, settings)

    service.check_now()

    assert fake_sm.paused == []


def test_no_battery_sensor_is_a_noop(monkeypatch):
    monkeypatch.setattr(bps_module.psutil, "sensors_battery", lambda: None)
    settings = _settings(enabled=True)
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(info_hash="abc")]
    service = BatteryPauseService(fake_sm, settings)

    service.check_now()

    assert fake_sm.paused == []


def test_pauses_active_downloads_on_unplug(monkeypatch):
    monkeypatch.setattr(bps_module.psutil, "sensors_battery", lambda: FakeBattery(power_plugged=False))
    settings = _settings(enabled=True)
    fake_sm = FakeSessionManager()
    fake_sm.records = [
        FakeRecord(info_hash="downloading", state=TorrentState.DOWNLOADING),
        FakeRecord(info_hash="queued", state=TorrentState.QUEUED),
        FakeRecord(info_hash="already-seeding", state=TorrentState.SEEDING),
    ]
    service = BatteryPauseService(fake_sm, settings)

    service.check_now()

    assert set(fake_sm.paused) == {"downloading", "queued"}


def test_resumes_only_torrents_this_service_paused(monkeypatch):
    settings = _settings(enabled=True)
    fake_sm = FakeSessionManager()
    # "manual" was already paused by the user before the machine was ever
    # unplugged -- the service must never touch it.
    fake_sm.records = [
        FakeRecord(info_hash="downloading", state=TorrentState.DOWNLOADING),
        FakeRecord(info_hash="manual", state=TorrentState.PAUSED),
    ]
    service = BatteryPauseService(fake_sm, settings)

    monkeypatch.setattr(bps_module.psutil, "sensors_battery", lambda: FakeBattery(power_plugged=False))
    service.check_now()  # unplug -- pauses "downloading" only

    monkeypatch.setattr(bps_module.psutil, "sensors_battery", lambda: FakeBattery(power_plugged=True))
    service.check_now()  # replug -- must resume exactly what it paused

    assert fake_sm.resumed == ["downloading"]
    assert "manual" not in fake_sm.resumed


def test_paused_set_is_cleared_after_resume(monkeypatch):
    settings = _settings(enabled=True)
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(info_hash="downloading", state=TorrentState.DOWNLOADING)]
    service = BatteryPauseService(fake_sm, settings)

    monkeypatch.setattr(bps_module.psutil, "sensors_battery", lambda: FakeBattery(power_plugged=False))
    service.check_now()
    monkeypatch.setattr(bps_module.psutil, "sensors_battery", lambda: FakeBattery(power_plugged=True))
    service.check_now()
    fake_sm.resumed.clear()

    service.check_now()  # still plugged in, nothing left to resume

    assert fake_sm.resumed == []
