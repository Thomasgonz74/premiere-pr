import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.main_window import MainWindow


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_window(session_manager, stats_service):
    return MainWindow(
        session_manager,
        stats_service,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        Settings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )


def test_close_event_shuts_down_stats_and_session():
    session_manager = MagicMock()
    stats_service = MagicMock()
    call_order = []
    stats_service.shutdown.side_effect = lambda: call_order.append("stats_service")
    session_manager.shutdown.side_effect = lambda: call_order.append("session_manager")

    win = _make_window(session_manager, stats_service)
    try:
        win.close()  # goes through Qt's real close path, which dispatches closeEvent

        stats_service.shutdown.assert_called_once()
        session_manager.shutdown.assert_called_once()
        # closeEvent runs stats_service.shutdown() before session_manager.shutdown(),
        # but that order is incidental rather than a real dependency: StatsService's
        # shutdown() calls flush(), which only reads its own self._current dict --
        # populated earlier via the torrent_status_updated signal -- and never queries
        # session_manager live. So session_manager.shutdown() (which stops timers and
        # persists resume data) running first would not break stats flushing. Asserted
        # anyway so a reorder shows up as a visible diff here rather than nowhere.
        assert call_order == ["stats_service", "session_manager"]
    finally:
        win.close()
