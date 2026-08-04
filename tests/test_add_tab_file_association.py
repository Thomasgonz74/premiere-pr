import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.tabs.add_tab import AddTorrentTab


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab():
    return AddTorrentTab(MagicMock(), Settings())


def test_open_torrent_file_prefills_the_form_like_a_manual_browse(tab):
    tab.open_torrent_file(r"C:\Users\thoma\Downloads\ubuntu.torrent")
    assert tab.selected_file_label.text() == r"C:\Users\thoma\Downloads\ubuntu.torrent"
    assert tab._torrent_path == r"C:\Users\thoma\Downloads\ubuntu.torrent"
    assert tab.magnet_input.text() == ""


def test_open_magnet_prefills_the_magnet_field(tab):
    uri = "magnet:?xt=urn:btih:abc123"
    tab.open_magnet(uri)
    assert tab.magnet_input.text() == uri
    assert tab._torrent_path is None
    assert tab.selected_file_label.text() == ""


def test_opening_a_torrent_file_clears_any_previous_magnet_state(tab):
    tab.open_magnet("magnet:?xt=urn:btih:abc123")
    tab.open_torrent_file(r"C:\path\to\file.torrent")
    assert tab.magnet_input.text() == ""
    assert tab._torrent_path == r"C:\path\to\file.torrent"


def test_opening_a_magnet_clears_any_previous_torrent_file_state(tab):
    tab.open_torrent_file(r"C:\path\to\file.torrent")
    tab.open_magnet("magnet:?xt=urn:btih:abc123")
    assert tab._torrent_path is None
    assert tab.selected_file_label.text() == ""
