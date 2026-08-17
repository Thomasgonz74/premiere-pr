import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.danger_scanner.models import FileEntry
from torrent2000.ui.tabs.add_tab import AddTorrentTab

TORRENT_PATH = r"C:\path\to\file.torrent"
DEST = r"C:\destination"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab():
    # open_torrent_file() now triggers an automatic scan; TORRENT_PATH is a
    # fake path, so stub the reader just for this initial selection -- each
    # test below patches it again with its own fixture data for the
    # _on_start_clicked() call.
    t = AddTorrentTab(MagicMock(), Settings())
    with patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[]):
        t.open_torrent_file(TORRENT_PATH)
    t.dest_input.setText(DEST)
    return t


def test_duplicate_torrent_shows_information_dialog_instead_of_crashing(tab):
    tab._session_manager.add_torrent_from_file.side_effect = RuntimeError("duplicate torrent is already in session")

    with (
        patch(
            "torrent2000.ui.tabs.add_tab.files_from_torrent_path",
            return_value=[FileEntry(index=0, path="a.bin", size=100)],
        ),
        patch("torrent2000.ui.tabs.add_tab.free_space_mb", return_value=10_000.0),
        patch("torrent2000.ui.tabs.add_tab.QMessageBox") as mock_box,
    ):
        tab._on_start_clicked()

    mock_box.information.assert_called_once()
    mock_box.warning.assert_not_called()
    tab._session_manager.add_torrent_from_file.assert_called_once_with(TORRENT_PATH, DEST, set())


def test_insufficient_disk_space_blocks_start_before_adding_the_torrent(tab):
    big_file = FileEntry(index=0, path="a.bin", size=500 * 1024 * 1024)

    with (
        patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[big_file]),
        patch("torrent2000.ui.tabs.add_tab.free_space_mb", return_value=10.0),
        patch("torrent2000.ui.tabs.add_tab.QMessageBox") as mock_box,
    ):
        tab._on_start_clicked()

    mock_box.warning.assert_called_once()
    mock_box.information.assert_not_called()
    tab._session_manager.add_torrent_from_file.assert_not_called()


def test_enough_disk_space_starts_the_torrent_normally(tab):
    small_file = FileEntry(index=0, path="a.bin", size=100)

    with (
        patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[small_file]),
        patch("torrent2000.ui.tabs.add_tab.free_space_mb", return_value=10_000.0),
        patch("torrent2000.ui.tabs.add_tab.QMessageBox") as mock_box,
    ):
        tab._on_start_clicked()

    tab._session_manager.add_torrent_from_file.assert_called_once_with(TORRENT_PATH, DEST, set())
    mock_box.warning.assert_not_called()
    mock_box.information.assert_not_called()


def test_starting_after_a_torrent_file_that_fails_to_parse_shows_warning_instead_of_crashing(tab):
    """Regression test: selecting a corrupted/invalid .torrent leaves
    self._torrent_path set even though _analyze_file_source's own
    files_from_torrent_path() call already failed gracefully. Démarrer must
    re-read the file for its disk-space check through the same guarded path
    instead of letting the RuntimeError escape uncaught."""
    with (
        patch(
            "torrent2000.ui.tabs.add_tab.files_from_torrent_path",
            side_effect=RuntimeError("expected value (list, dict, int or string) in bencoded string [bdecode:4]"),
        ),
        patch("torrent2000.ui.tabs.add_tab.QMessageBox") as mock_box,
    ):
        tab._on_start_clicked()

    mock_box.warning.assert_called_once()
    mock_box.information.assert_not_called()
    tab._session_manager.add_torrent_from_file.assert_not_called()
