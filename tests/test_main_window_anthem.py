import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.theme_ids import CCCP_THEME_ID
from torrent2000.ui.main_window import MainWindow


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    win = MainWindow(
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        Settings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    win._anthem_player = MagicMock()
    yield win
    win.close()


def test_anthem_starts_when_switching_to_cccp_theme(window):
    window._apply_window_style(CCCP_THEME_ID, "light")
    window._anthem_player.start.assert_called_once()
    window._anthem_player.stop.assert_not_called()


def test_anthem_stops_when_switching_away_from_cccp_theme(window):
    window._apply_window_style(CCCP_THEME_ID, "light")
    window._anthem_player.reset_mock()

    window._apply_window_style("luna_xp", "light")

    window._anthem_player.stop.assert_called_once()
    window._anthem_player.start.assert_not_called()


def test_switching_to_cccp_twice_does_not_restart_playback(window):
    window._apply_window_style(CCCP_THEME_ID, "light")
    window._anthem_player.reset_mock()

    window._apply_window_style(CCCP_THEME_ID, "dark")  # appearance change, still CCCP

    window._anthem_player.start.assert_not_called()
    window._anthem_player.stop.assert_not_called()


def test_profile_tab_volume_changes_propagate_to_anthem_player():
    # Uses the real AnthemPlayer (not the mock-swapped `window` fixture)
    # since the signal was connected to its bound method at construction
    # time -- swapping the attribute afterwards wouldn't rewire that connection.
    win = MainWindow(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        Settings(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
    )
    win._profile_tab.volume_changed.emit(33)
    assert win._anthem_player._audio_output.volume() == pytest.approx(0.33)
    win.close()
