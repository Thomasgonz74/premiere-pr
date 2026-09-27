"""Coverage for NotificationService's relay of two previously-orphaned
SessionManager signals (theme_downloads_paused, storage_moved) to a toast --
mirrors test_notifications_file_error.py's fixture structure exactly."""

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
    theme_downloads_paused = Signal(int)
    storage_moved = Signal(str, str)

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


def test_theme_downloads_paused_surfaces_a_toast(notification_service):
    _service, session_manager, mock_tray = notification_service

    session_manager.theme_downloads_paused.emit(3)

    mock_tray.showMessage.assert_called_once()
    title, message = mock_tray.showMessage.call_args[0][:2]
    assert title == "Téléchargements mis en pause"
    assert "3" in message


def test_theme_downloads_paused_zero_count_is_a_noop(notification_service):
    _service, session_manager, mock_tray = notification_service

    session_manager.theme_downloads_paused.emit(0)

    mock_tray.showMessage.assert_not_called()


def test_storage_moved_surfaces_a_toast_with_torrent_name_and_new_path(notification_service):
    _service, session_manager, mock_tray = notification_service

    session_manager.storage_moved.emit("abc123", "D:/NewLocation")

    mock_tray.showMessage.assert_called_once()
    title, message = mock_tray.showMessage.call_args[0][:2]
    assert title == "Déplacement terminé"
    assert message == "Example.Torrent -- nouveau chemin : D:/NewLocation"


def test_storage_moved_unknown_info_hash_falls_back_to_truncated_hash(notification_service):
    _service, session_manager, mock_tray = notification_service

    session_manager.storage_moved.emit("unknownhash123456", "D:/NewLocation")

    mock_tray.showMessage.assert_called_once()
    _title, message = mock_tray.showMessage.call_args[0][:2]
    assert "unknownhash1" in message
