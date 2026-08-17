import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from torrent2000 import app as app_module


def test_main_exits_early_without_starting_a_session_when_another_instance_is_running(monkeypatch):
    # Everything from _setup_logging() onward touches real machine state
    # (log files, %APPDATA%\Torrent2000\config.json, a libtorrent session)
    # -- mocked here so the assertions below prove main() never reaches any
    # of it, not just that the mocks happen to be harmless if it did.
    monkeypatch.setattr(sys, "argv", ["torrent2000", "C:/downloads/example.torrent"])

    mock_qapp_instance = MagicMock()
    mock_guard_instance = MagicMock()
    mock_guard_instance.try_become_primary.return_value = False

    with (
        patch.object(app_module, "QApplication", MagicMock(return_value=mock_qapp_instance)),
        patch.object(app_module, "SingleInstanceGuard", MagicMock(return_value=mock_guard_instance)),
        patch.object(app_module, "_setup_logging") as mock_setup_logging,
        patch.object(app_module, "Settings") as mock_settings,
        patch.object(app_module, "SessionManager") as mock_session_manager,
        patch.object(app_module, "MainWindow") as mock_main_window,
    ):
        result = app_module.main()

    assert result == 0
    mock_guard_instance.try_become_primary.assert_called_once_with("C:/downloads/example.torrent")
    mock_setup_logging.assert_not_called()
    mock_settings.load.assert_not_called()
    mock_session_manager.assert_not_called()
    mock_main_window.assert_not_called()


def test_main_forwards_empty_string_when_a_second_launch_has_no_argument(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["torrent2000"])

    mock_qapp_instance = MagicMock()
    mock_guard_instance = MagicMock()
    mock_guard_instance.try_become_primary.return_value = False

    with (
        patch.object(app_module, "QApplication", MagicMock(return_value=mock_qapp_instance)),
        patch.object(app_module, "SingleInstanceGuard", MagicMock(return_value=mock_guard_instance)),
        patch.object(app_module, "_setup_logging"),
        patch.object(app_module, "Settings"),
        patch.object(app_module, "SessionManager") as mock_session_manager,
        patch.object(app_module, "MainWindow") as mock_main_window,
    ):
        result = app_module.main()

    assert result == 0
    mock_guard_instance.try_become_primary.assert_called_once_with("")
    mock_session_manager.assert_not_called()
    mock_main_window.assert_not_called()
