"""Coverage for WebhookNotificationService: schedules a webhook POST for the
same events NotificationService already shows as a toast, only when
Settings.webhook_enabled and webhook_url are both set (see
engine/webhook_notification_service.py)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.webhook_notification_service import WebhookNotificationService


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class FakeRecord:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeSessionManager(QObject):
    torrent_finished = Signal(str)
    tracker_error = Signal(str, str)
    file_error = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.records: dict[str, FakeRecord] = {}

    def get_record(self, info_hash: str):
        return self.records.get(info_hash)


class FakeShareLimitService(QObject):
    limit_reached = Signal(str, str)


class _CapturingThreadPool:
    def __init__(self):
        self.started = []

    def start(self, runnable, priority=0):
        self.started.append(runnable)


@pytest.fixture
def wired(monkeypatch):
    pool = _CapturingThreadPool()
    monkeypatch.setattr(
        "torrent2000.engine.webhook_notification_service.QThreadPool.globalInstance", staticmethod(lambda: pool)
    )
    session_manager = FakeSessionManager()
    session_manager.records["abc123"] = FakeRecord("Example.Torrent")
    share_limit_service = FakeShareLimitService()
    settings = Settings()
    settings.webhook_enabled = True
    settings.webhook_url = "https://ntfy.sh/my-topic"
    service = WebhookNotificationService(session_manager, share_limit_service, settings)
    return service, session_manager, share_limit_service, settings, pool


def test_torrent_finished_schedules_a_webhook_post(wired):
    _service, session_manager, _sls, _settings, pool = wired

    session_manager.torrent_finished.emit("abc123")

    assert len(pool.started) == 1
    assert "Example.Torrent" in pool.started[0]._message
    assert pool.started[0]._url == "https://ntfy.sh/my-topic"


def test_disabled_setting_sends_nothing(wired):
    _service, session_manager, _sls, settings, pool = wired
    settings.webhook_enabled = False

    session_manager.torrent_finished.emit("abc123")

    assert pool.started == []


def test_empty_url_sends_nothing(wired):
    _service, session_manager, _sls, settings, pool = wired
    settings.webhook_url = ""

    session_manager.torrent_finished.emit("abc123")

    assert pool.started == []


def test_limit_reached_schedules_a_webhook_post(wired):
    _service, _sm, share_limit_service, _settings, pool = wired

    share_limit_service.limit_reached.emit("abc123", "ratio")

    assert len(pool.started) == 1
    assert "ratio" in pool.started[0]._message
