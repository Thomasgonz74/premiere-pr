from dataclasses import dataclass

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import memory_pressure_governor as mpg_module
from torrent2000.engine.memory_pressure_governor import MemoryPressureGovernor


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@dataclass
class FakeVirtualMemory:
    percent: float


class FakeSessionManager:
    def __init__(self):
        self.max_active_calls: list[int] = []

    def set_max_active_downloads(self, count: int) -> None:
        self.max_active_calls.append(count)


class FakeRssFeedService:
    def __init__(self):
        self.paused_calls: list[bool] = []

    def set_paused(self, paused: bool) -> None:
        self.paused_calls.append(paused)


class FakeHistoryService:
    def __init__(self):
        self.paused_calls: list[bool] = []

    def set_paused(self, paused: bool) -> None:
        self.paused_calls.append(paused)


def _settings(enabled: bool = True, threshold: int = 90, max_active: int = 8) -> Settings:
    settings = Settings()
    settings.memory_governor_enabled = enabled
    settings.memory_governor_threshold_percent = threshold
    settings.max_active_downloads = max_active
    return settings


def _make(settings):
    session_manager = FakeSessionManager()
    rss = FakeRssFeedService()
    history = FakeHistoryService()
    governor = MemoryPressureGovernor(session_manager, settings, rss, history)
    return governor, session_manager, rss, history


def test_disabled_by_default_does_nothing_under_pressure(monkeypatch):
    monkeypatch.setattr(mpg_module.psutil, "virtual_memory", lambda: FakeVirtualMemory(percent=99))
    settings = _settings(enabled=False)
    governor, session_manager, rss, history = _make(settings)

    governor.check_now()

    assert session_manager.max_active_calls == []
    assert rss.paused_calls == []
    assert history.paused_calls == []


def test_below_threshold_does_nothing(monkeypatch):
    monkeypatch.setattr(mpg_module.psutil, "virtual_memory", lambda: FakeVirtualMemory(percent=50))
    settings = _settings(enabled=True, threshold=90)
    governor, session_manager, rss, history = _make(settings)

    governor.check_now()

    assert session_manager.max_active_calls == []
    assert rss.paused_calls == []
    assert history.paused_calls == []


def test_over_threshold_halves_active_downloads_and_pauses_services(monkeypatch):
    monkeypatch.setattr(mpg_module.psutil, "virtual_memory", lambda: FakeVirtualMemory(percent=95))
    settings = _settings(enabled=True, threshold=90, max_active=8)
    governor, session_manager, rss, history = _make(settings)

    governor.check_now()

    assert session_manager.max_active_calls == [4]
    assert rss.paused_calls == [True]
    assert history.paused_calls == [True]


def test_low_max_active_downloads_never_reduced_below_one(monkeypatch):
    monkeypatch.setattr(mpg_module.psutil, "virtual_memory", lambda: FakeVirtualMemory(percent=95))
    settings = _settings(enabled=True, threshold=90, max_active=1)
    governor, session_manager, rss, history = _make(settings)

    governor.check_now()

    assert session_manager.max_active_calls == [1]


def test_repeated_ticks_over_threshold_do_not_reapply_pressure(monkeypatch):
    monkeypatch.setattr(mpg_module.psutil, "virtual_memory", lambda: FakeVirtualMemory(percent=95))
    settings = _settings(enabled=True, threshold=90, max_active=8)
    governor, session_manager, rss, history = _make(settings)

    governor.check_now()
    governor.check_now()
    governor.check_now()

    # Only applied once -- not stacked further on every subsequent tick.
    assert session_manager.max_active_calls == [4]
    assert rss.paused_calls == [True]
    assert history.paused_calls == [True]


def test_dropping_back_below_threshold_restores_everything(monkeypatch):
    settings = _settings(enabled=True, threshold=90, max_active=8)
    governor, session_manager, rss, history = _make(settings)

    monkeypatch.setattr(mpg_module.psutil, "virtual_memory", lambda: FakeVirtualMemory(percent=95))
    governor.check_now()  # pressure applied

    monkeypatch.setattr(mpg_module.psutil, "virtual_memory", lambda: FakeVirtualMemory(percent=50))
    governor.check_now()  # pressure eases

    assert session_manager.max_active_calls == [4, 8]
    assert rss.paused_calls == [True, False]
    assert history.paused_calls == [True, False]


def test_disabling_mid_throttle_restores_everything(monkeypatch):
    settings = _settings(enabled=True, threshold=90, max_active=8)
    governor, session_manager, rss, history = _make(settings)

    monkeypatch.setattr(mpg_module.psutil, "virtual_memory", lambda: FakeVirtualMemory(percent=95))
    governor.check_now()  # pressure applied

    settings.memory_governor_enabled = False
    governor.check_now()  # user opted back out mid-throttle

    assert session_manager.max_active_calls == [4, 8]
    assert rss.paused_calls == [True, False]
    assert history.paused_calls == [True, False]
