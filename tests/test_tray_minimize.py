import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.main_window import MainWindow


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_window(settings):
    stats_service = MagicMock()
    session_manager = MagicMock()
    win = MainWindow(
        session_manager,
        stats_service,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        settings,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    return win, stats_service, session_manager


def test_close_minimizes_to_tray_when_enabled_and_available():
    settings = Settings()
    settings.minimize_to_tray = True
    win, stats_service, session_manager = _make_window(settings)
    try:
        with patch("torrent2000.ui.main_window.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
            win.close()
        assert win.isHidden()
        stats_service.shutdown.assert_not_called()
        session_manager.shutdown.assert_not_called()
        assert win._shutdown_done is False
    finally:
        win._shutdown_done = True  # skip real teardown, nothing was started
        win.deleteLater()


def test_close_shuts_down_fully_when_minimize_to_tray_disabled():
    settings = Settings()
    settings.minimize_to_tray = False
    win, stats_service, session_manager = _make_window(settings)
    with patch("torrent2000.ui.main_window.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
        win.close()
    stats_service.shutdown.assert_called_once()
    session_manager.shutdown.assert_called_once()
    assert win._shutdown_done is True


def test_about_to_quit_is_a_noop_if_close_event_already_shut_down():
    settings = Settings()
    settings.minimize_to_tray = False
    win, stats_service, session_manager = _make_window(settings)
    with patch("torrent2000.ui.main_window.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
        win.close()
    win._on_about_to_quit()
    stats_service.shutdown.assert_called_once()
    session_manager.shutdown.assert_called_once()


def test_about_to_quit_shuts_down_once_when_close_event_only_minimized():
    settings = Settings()
    settings.minimize_to_tray = True
    win, stats_service, session_manager = _make_window(settings)
    try:
        with patch("torrent2000.ui.main_window.QSystemTrayIcon.isSystemTrayAvailable", return_value=True):
            win.close()  # minimizes to tray, no shutdown yet
        win._on_about_to_quit()  # tray menu's "Quitter" -> app.quit() -> aboutToQuit
        stats_service.shutdown.assert_called_once()
        session_manager.shutdown.assert_called_once()
        win._on_about_to_quit()  # a second aboutToQuit must not double-shutdown
        stats_service.shutdown.assert_called_once()
        session_manager.shutdown.assert_called_once()
    finally:
        win.deleteLater()
