import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import idle_activity_service as ias_module
from torrent2000.engine.idle_activity_service import IdleActivityService


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class FakeBandwidthScheduler:
    def __init__(self):
        self.turtle_calls: list[bool] = []

    def set_turtle_mode(self, enabled: bool, *args, **kwargs) -> None:
        self.turtle_calls.append(enabled)


def _settings(enabled: bool = True, minutes: int = 15) -> Settings:
    settings = Settings()
    settings.idle_bandwidth_reduction_enabled = enabled
    settings.idle_bandwidth_reduction_minutes = minutes
    return settings


def _make(settings):
    scheduler = FakeBandwidthScheduler()
    service = IdleActivityService(scheduler, settings)
    return service, scheduler


def test_disabled_by_default_does_nothing_when_idle(monkeypatch):
    monkeypatch.setattr(ias_module, "idle_ms", lambda: 999_999_999)
    settings = _settings(enabled=False)
    service, scheduler = _make(settings)

    service.check_now()

    assert scheduler.turtle_calls == []


def test_idle_query_failure_is_a_noop(monkeypatch):
    monkeypatch.setattr(ias_module, "idle_ms", lambda: None)
    settings = _settings(enabled=True)
    service, scheduler = _make(settings)

    service.check_now()

    assert scheduler.turtle_calls == []


def test_below_threshold_does_nothing(monkeypatch):
    monkeypatch.setattr(ias_module, "idle_ms", lambda: 60_000)  # 1 minute idle
    settings = _settings(enabled=True, minutes=15)
    service, scheduler = _make(settings)

    service.check_now()

    assert scheduler.turtle_calls == []


def test_over_threshold_engages_turtle_mode(monkeypatch):
    monkeypatch.setattr(ias_module, "idle_ms", lambda: 16 * 60_000)  # 16 minutes idle
    settings = _settings(enabled=True, minutes=15)
    service, scheduler = _make(settings)

    service.check_now()

    assert scheduler.turtle_calls == [True]


def test_repeated_idle_ticks_do_not_reapply(monkeypatch):
    monkeypatch.setattr(ias_module, "idle_ms", lambda: 16 * 60_000)
    settings = _settings(enabled=True, minutes=15)
    service, scheduler = _make(settings)

    service.check_now()
    service.check_now()
    service.check_now()

    assert scheduler.turtle_calls == [True]


def test_activity_resuming_disables_turtle_mode(monkeypatch):
    settings = _settings(enabled=True, minutes=15)
    service, scheduler = _make(settings)

    monkeypatch.setattr(ias_module, "idle_ms", lambda: 16 * 60_000)
    service.check_now()  # goes idle -- turtle on

    monkeypatch.setattr(ias_module, "idle_ms", lambda: 0)
    service.check_now()  # activity resumes -- turtle off

    assert scheduler.turtle_calls == [True, False]


def test_disabling_mid_idle_restores(monkeypatch):
    settings = _settings(enabled=True, minutes=15)
    service, scheduler = _make(settings)

    monkeypatch.setattr(ias_module, "idle_ms", lambda: 16 * 60_000)
    service.check_now()  # goes idle -- turtle on

    settings.idle_bandwidth_reduction_enabled = False
    service.check_now()  # user opted back out mid-idle

    assert scheduler.turtle_calls == [True, False]


def test_idle_ms_handles_tick_wraparound(monkeypatch):
    # GetTickCount() wrapped past 2**32 while dwTime was recorded just before
    # the wrap -- unsigned 32-bit subtraction must still give a small,
    # correct idle duration instead of a huge negative-looking number.
    fake_info = ias_module._LastInputInfo()
    fake_info.dwTime = (2**32) - 100  # last input just before wraparound

    class FakeUser32:
        @staticmethod
        def GetLastInputInfo(ptr):
            ptr._obj.dwTime = fake_info.dwTime
            ptr._obj.cbSize = fake_info.cbSize
            return 1

    class FakeKernel32:
        @staticmethod
        def GetTickCount():
            return 50  # wrapped around and ticked another 50ms since

    class FakeWindll:
        user32 = FakeUser32()
        kernel32 = FakeKernel32()

    monkeypatch.setattr(ias_module.ctypes, "windll", FakeWindll(), raising=False)

    assert ias_module.idle_ms() == 150  # 100ms to the wrap + 50ms after it
