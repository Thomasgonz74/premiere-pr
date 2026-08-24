import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.notifications import NotificationService


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
    torrent_removed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.records: dict[str, FakeRecord] = {}

    def get_record(self, info_hash: str):
        return self.records.get(info_hash)


class FakeShareLimitService(QObject):
    limit_reached = Signal(str, str)


@pytest.fixture
def notification_service():
    session_manager = FakeSessionManager()
    session_manager.records["abc123"] = FakeRecord("Example.Torrent")
    share_limit_service = FakeShareLimitService()
    settings = Settings()
    settings.notifications_enabled = True

    with patch("torrent2000.ui.notifications.QSystemTrayIcon") as mock_tray_cls:
        mock_tray_cls.isSystemTrayAvailable.return_value = True
        mock_tray_instance = MagicMock()
        mock_tray_cls.return_value = mock_tray_instance
        service = NotificationService(session_manager, share_limit_service, settings)
        yield service, session_manager, mock_tray_instance


def test_tracker_error_surfaces_a_toast_notification(notification_service):
    _service, session_manager, mock_tray = notification_service

    session_manager.tracker_error.emit("abc123", "connection timed out")

    mock_tray.showMessage.assert_called_once()
    title, message = mock_tray.showMessage.call_args[0][:2]
    assert title == "Erreur de tracker"
    assert message == "Example.Torrent -- connection timed out"


def test_tracker_error_for_unknown_torrent_falls_back_to_truncated_hash(notification_service):
    _service, session_manager, mock_tray = notification_service

    session_manager.tracker_error.emit("deadbeefdeadbeefdead", "unreachable")

    mock_tray.showMessage.assert_called_once()
    _title, message = mock_tray.showMessage.call_args[0][:2]
    assert message == "deadbeefdead -- unreachable"


def test_repeated_tracker_errors_for_the_same_torrent_are_suppressed(notification_service):
    _service, session_manager, mock_tray = notification_service

    session_manager.tracker_error.emit("abc123", "connection timed out")
    session_manager.tracker_error.emit("abc123", "connection timed out")
    session_manager.tracker_error.emit("abc123", "a different error message")

    mock_tray.showMessage.assert_called_once()


def test_tracker_error_notifications_resume_after_the_torrent_is_removed(notification_service):
    _service, session_manager, mock_tray = notification_service

    session_manager.tracker_error.emit("abc123", "connection timed out")
    session_manager.torrent_removed.emit("abc123")
    session_manager.tracker_error.emit("abc123", "connection timed out")

    assert mock_tray.showMessage.call_count == 2


def test_a_different_torrents_tracker_error_is_not_suppressed(notification_service):
    _service, session_manager, mock_tray = notification_service
    session_manager.records["other456"] = FakeRecord("Other.Torrent")

    session_manager.tracker_error.emit("abc123", "connection timed out")
    session_manager.tracker_error.emit("other456", "connection timed out")

    assert mock_tray.showMessage.call_count == 2
