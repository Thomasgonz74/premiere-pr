from dataclasses import dataclass, field

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.auto_shutdown_service import AutoShutdownService, all_torrents_idle
from torrent2000.engine.torrent_item import TorrentState


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@dataclass
class FakeRecord:
    info_hash: str = "abc"
    state: TorrentState = TorrentState.DOWNLOADING


class FakeSessionManager(QObject):
    torrent_finished = Signal(str)

    def __init__(self):
        super().__init__()
        self.records: list = []

    def all_records(self):
        return list(self.records)


# ------------------------------------------------------------ pure function


def test_all_torrents_idle_true_when_empty():
    assert all_torrents_idle([]) is True


def test_all_torrents_idle_true_when_only_finished_or_paused():
    records = [FakeRecord(state=TorrentState.FINISHED), FakeRecord(state=TorrentState.PAUSED)]
    assert all_torrents_idle(records) is True


def test_all_torrents_idle_true_when_seeding_or_errored():
    records = [FakeRecord(state=TorrentState.SEEDING), FakeRecord(state=TorrentState.ERROR)]
    assert all_torrents_idle(records) is True


@pytest.mark.parametrize(
    "active_state", [TorrentState.DOWNLOADING, TorrentState.QUEUED, TorrentState.CHECKING_METADATA]
)
def test_all_torrents_idle_false_when_one_still_active(active_state):
    records = [FakeRecord(state=TorrentState.FINISHED), FakeRecord(state=active_state)]
    assert all_torrents_idle(records) is False


# --------------------------------------------------------------------- service


def _make_settings(**overrides) -> Settings:
    settings = Settings()
    settings.auto_shutdown_enabled = overrides.get("auto_shutdown_enabled", True)
    settings.auto_shutdown_action = overrides.get("auto_shutdown_action", "shutdown")
    settings.auto_shutdown_delay_seconds = overrides.get("auto_shutdown_delay_seconds", 60)
    return settings


def test_disabled_by_default_never_starts_countdown():
    settings = Settings()
    assert settings.auto_shutdown_enabled is False

    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(state=TorrentState.FINISHED)]
    service = AutoShutdownService(fake_sm, settings)

    started = []
    service.shutdown_countdown_started.connect(started.append)
    fake_sm.torrent_finished.emit("abc")

    assert started == []


def test_countdown_starts_when_enabled_and_all_idle():
    settings = _make_settings(auto_shutdown_delay_seconds=42)
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(state=TorrentState.FINISHED)]
    service = AutoShutdownService(fake_sm, settings)

    started = []
    service.shutdown_countdown_started.connect(started.append)
    fake_sm.torrent_finished.emit("abc")

    assert started == [42]


def test_countdown_does_not_start_when_another_torrent_still_downloading():
    settings = _make_settings()
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(info_hash="finished", state=TorrentState.FINISHED),
                        FakeRecord(info_hash="active", state=TorrentState.DOWNLOADING)]
    service = AutoShutdownService(fake_sm, settings)

    started = []
    service.shutdown_countdown_started.connect(started.append)
    fake_sm.torrent_finished.emit("finished")

    assert started == []


def test_elapsed_countdown_executes_with_configured_action(monkeypatch):
    settings = _make_settings(auto_shutdown_action="hibernate")
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(state=TorrentState.FINISHED)]
    service = AutoShutdownService(fake_sm, settings)

    executed = []
    monkeypatch.setattr(service, "_execute", lambda action: executed.append(action))

    fake_sm.torrent_finished.emit("abc")
    service._on_countdown_elapsed()  # simulate the countdown timer firing

    assert executed == ["hibernate"]


def test_cancel_shutdown_prevents_execution(monkeypatch):
    settings = _make_settings()
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(state=TorrentState.FINISHED)]
    service = AutoShutdownService(fake_sm, settings)

    executed = []
    monkeypatch.setattr(service, "_execute", lambda action: executed.append(action))

    fake_sm.torrent_finished.emit("abc")
    service.cancel_shutdown()
    service._on_countdown_elapsed()  # even if the timer had already fired

    assert executed == []


def test_setting_disabled_after_countdown_started_prevents_execution(monkeypatch):
    settings = _make_settings()
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(state=TorrentState.FINISHED)]
    service = AutoShutdownService(fake_sm, settings)

    executed = []
    monkeypatch.setattr(service, "_execute", lambda action: executed.append(action))

    fake_sm.torrent_finished.emit("abc")
    settings.auto_shutdown_enabled = False  # user (or another code path) disabled it mid-countdown
    service._on_countdown_elapsed()

    assert executed == []


def test_second_finish_event_does_not_start_a_second_countdown():
    settings = _make_settings()
    fake_sm = FakeSessionManager()
    fake_sm.records = [FakeRecord(state=TorrentState.FINISHED)]
    service = AutoShutdownService(fake_sm, settings)

    started = []
    service.shutdown_countdown_started.connect(started.append)
    fake_sm.torrent_finished.emit("abc")
    fake_sm.torrent_finished.emit("abc")

    assert started == [settings.auto_shutdown_delay_seconds]
