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

# Double extension (.pdf.exe) + executable extension rules together score
# well above the default danger_auto_exclude_threshold of 60.
RISKY_FILE = FileEntry(index=0, path="invoice.pdf.exe", size=50_000)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tab():
    return AddTorrentTab(MagicMock(), Settings())


# ------------------------------------------------------------- file source


def test_selecting_torrent_file_auto_analyzes_without_clicking_analyser(tab):
    with patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[RISKY_FILE]):
        tab.open_torrent_file(TORRENT_PATH)

    assert tab.file_tree.topLevelItemCount() == 1
    assert tab.file_tree.excluded_indices() == {0}
    assert tab.status_label.text() != ""


def test_drag_and_drop_selection_also_auto_analyzes(tab):
    with patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[RISKY_FILE]):
        tab._on_torrent_file_selected(TORRENT_PATH)

    assert tab.file_tree.topLevelItemCount() == 1
    assert tab.file_tree.excluded_indices() == {0}


def test_manual_analyze_after_auto_analysis_is_idempotent(tab):
    with patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[RISKY_FILE]):
        tab.open_torrent_file(TORRENT_PATH)
        assert tab.file_tree.topLevelItemCount() == 1

        # Clicking "Analyser" again after the automatic scan must not
        # duplicate rows or otherwise misbehave.
        tab._on_analyze_clicked()

    assert tab.file_tree.topLevelItemCount() == 1
    assert tab.file_tree.excluded_indices() == {0}


def test_starting_immediately_after_selection_applies_the_auto_exclusion(tab):
    """The scenario from the audit finding: select a file and click
    Démarrer straight away, with no explicit Analyser click in between."""
    with patch("torrent2000.ui.tabs.add_tab.files_from_torrent_path", return_value=[RISKY_FILE]):
        tab.open_torrent_file(TORRENT_PATH)
        tab.dest_input.setText(DEST)

        with (
            patch("torrent2000.ui.tabs.add_tab.free_space_mb", return_value=10_000.0),
            patch("torrent2000.ui.tabs.add_tab.QMessageBox"),
        ):
            tab._on_start_clicked()

    tab._session_manager.add_torrent_from_file.assert_called_once_with(TORRENT_PATH, DEST, {0})


# ----------------------------------------------------------- magnet source


def test_starting_a_fresh_magnet_awaits_metadata_instead_of_starting_blind(tab):
    """Clicking Démarrer on a magnet that was never analyzed must not start
    the torrent with zero exclusions -- it should add it and wait."""
    tab._session_manager.add_torrent_from_magnet.return_value = "abc123"
    tab.magnet_input.setText("magnet:?xt=urn:btih:abc123")
    tab.dest_input.setText(DEST)

    with patch("torrent2000.ui.tabs.add_tab.QMessageBox") as mock_box:
        tab._on_start_clicked()

    tab._session_manager.add_torrent_from_magnet.assert_called_once()
    tab._session_manager.start_after_analysis.assert_not_called()
    tab._session_manager.exclude_files.assert_not_called()
    mock_box.information.assert_called_once()
    assert tab._pending_magnet_hash == "abc123"
    assert tab._magnet_metadata_ready is False


def test_second_start_click_before_metadata_arrives_still_refuses_to_start(tab):
    tab._session_manager.add_torrent_from_magnet.return_value = "abc123"
    tab.magnet_input.setText("magnet:?xt=urn:btih:abc123")
    tab.dest_input.setText(DEST)

    with patch("torrent2000.ui.tabs.add_tab.QMessageBox"):
        tab._on_start_clicked()
        tab._on_start_clicked()

    tab._session_manager.add_torrent_from_magnet.assert_called_once()
    tab._session_manager.start_after_analysis.assert_not_called()


def test_start_after_metadata_received_applies_exclusions_and_starts(tab):
    tab._session_manager.add_torrent_from_magnet.return_value = "abc123"
    tab._session_manager.get_torrent_files.return_value = [RISKY_FILE]
    tab.magnet_input.setText("magnet:?xt=urn:btih:abc123")
    tab.dest_input.setText(DEST)

    with patch("torrent2000.ui.tabs.add_tab.QMessageBox"):
        tab._on_start_clicked()  # adds and awaits metadata

    tab._on_metadata_received("abc123")  # simulate the async metadata signal
    assert tab.file_tree.excluded_indices() == {0}

    started = MagicMock()
    tab.torrent_started.connect(started)
    tab._on_start_clicked()  # second click, now allowed to actually start

    tab._session_manager.exclude_files.assert_called_once_with("abc123", {0})
    tab._session_manager.start_after_analysis.assert_called_once_with("abc123")
    started.assert_called_once()


def test_analyzer_button_on_a_magnet_still_works_like_before(tab):
    tab._session_manager.add_torrent_from_magnet.return_value = "abc123"
    tab.magnet_input.setText("magnet:?xt=urn:btih:abc123")

    tab._on_analyze_clicked()

    tab._session_manager.add_torrent_from_magnet.assert_called_once()
    assert tab._pending_magnet_hash == "abc123"
    assert tab.status_label.text() != ""
