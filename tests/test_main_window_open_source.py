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


@pytest.fixture
def window():
    win = MainWindow(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        Settings(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
    )
    # Spy on the real AddTorrentTab's methods rather than replacing the whole
    # widget -- open_source() also passes it to QTabWidget.setCurrentWidget(),
    # which requires an actual QWidget, not a bare MagicMock.
    win._add_tab.open_magnet = MagicMock()
    win._add_tab.open_torrent_file = MagicMock()
    yield win
    win.close()


def test_magnet_uri_routes_to_open_magnet(window):
    window.open_source("magnet:?xt=urn:btih:abc123")
    window._add_tab.open_magnet.assert_called_once_with("magnet:?xt=urn:btih:abc123")
    window._add_tab.open_torrent_file.assert_not_called()


def test_magnet_uri_is_case_insensitive(window):
    window.open_source("MAGNET:?xt=urn:btih:abc123")
    window._add_tab.open_magnet.assert_called_once()


def test_file_path_routes_to_open_torrent_file(window):
    window.open_source(r"C:\Users\thoma\Downloads\ubuntu.torrent")
    window._add_tab.open_torrent_file.assert_called_once_with(r"C:\Users\thoma\Downloads\ubuntu.torrent")
    window._add_tab.open_magnet.assert_not_called()


def test_switches_to_the_add_tab(window):
    window.open_source("magnet:?xt=urn:btih:abc123")
    assert window._tabs.currentWidget() is window._add_tab
