"""Regression tests for downloads_tab.py's "missing features" audit chapter:
search/filter bar, multi-selection support, the Category column, "Assign a
category..." and "Copy magnet link" context-menu actions."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetSelectionRange

from torrent2000.engine.torrent_item import TorrentRecord, TorrentState
from torrent2000.ui.tabs.downloads_tab import DownloadsTab

CATEGORY_COLUMN = 7


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_tab(*records: TorrentRecord) -> DownloadsTab:
    session_manager = MagicMock()
    session_manager.all_records.return_value = list(records)
    return DownloadsTab(session_manager)


def _select_rows(tab: DownloadsTab, *rows: int) -> None:
    tab.table.clearSelection()
    last_col = tab.table.columnCount() - 1
    for row in rows:
        tab.table.setRangeSelected(QTableWidgetSelectionRange(row, 0, row, last_col), True)


# --------------------------------------------------------------- search/filter

def test_filter_hides_non_matching_rows_case_insensitively():
    tab = _make_tab(
        TorrentRecord(info_hash="h1", name="Alpha Movie"),
        TorrentRecord(info_hash="h2", name="Beta Show"),
    )
    row_alpha = tab._rows["h1"]
    row_beta = tab._rows["h2"]

    tab.search_input.setText("ALPHA")

    assert tab.table.isRowHidden(row_alpha) is False
    assert tab.table.isRowHidden(row_beta) is True


def test_filter_cleared_reveals_every_row_again():
    tab = _make_tab(
        TorrentRecord(info_hash="h1", name="Alpha Movie"),
        TorrentRecord(info_hash="h2", name="Beta Show"),
    )
    row_alpha = tab._rows["h1"]
    row_beta = tab._rows["h2"]

    tab.search_input.setText("alpha")
    assert tab.table.isRowHidden(row_beta) is True

    tab.search_input.setText("")

    assert tab.table.isRowHidden(row_alpha) is False
    assert tab.table.isRowHidden(row_beta) is False


def test_filter_reapplied_after_a_new_row_is_added():
    tab = _make_tab(TorrentRecord(info_hash="h1", name="Alpha Movie"))
    tab.search_input.setText("alpha")

    new_record = TorrentRecord(info_hash="h2", name="Beta Show")
    tab._add_row(new_record)

    assert tab.table.isRowHidden(tab._rows["h2"]) is True


# ------------------------------------------------------------- multi-selection

def test_table_uses_extended_selection_mode():
    assert _make_tab().table.selectionMode() == QTableWidget.ExtendedSelection


def test_selection_changed_with_zero_rows_blanks_the_details_panel():
    tab = _make_tab(TorrentRecord(info_hash="h1", name="X"))
    _select_rows(tab, tab._rows["h1"])
    assert tab._selected_info_hash == "h1"

    tab.table.clearSelection()

    assert tab._selected_info_hash is None
    assert tab._current_record is None


def test_selection_changed_with_one_row_binds_that_torrent():
    tab = _make_tab(
        TorrentRecord(info_hash="h1", name="X"),
        TorrentRecord(info_hash="h2", name="Y"),
    )

    _select_rows(tab, tab._rows["h2"])

    assert tab._selected_info_hash == "h2"


def test_selection_changed_with_two_rows_blanks_the_details_panel_instead_of_crashing():
    tab = _make_tab(
        TorrentRecord(info_hash="h1", name="X"),
        TorrentRecord(info_hash="h2", name="Y"),
    )

    _select_rows(tab, tab._rows["h1"], tab._rows["h2"])

    assert tab._selected_info_hash is None
    assert tab._current_record is None
    assert set(tab._selected_info_hashes()) == {"h1", "h2"}


# ----------------------------------------------------------------- categories

def test_category_column_shows_record_category_on_add():
    tab = _make_tab(TorrentRecord(info_hash="h1", name="X", category="Movies"))
    row = tab._rows["h1"]

    assert tab.table.item(row, CATEGORY_COLUMN).text() == "Movies"


def test_category_column_updates_on_status_update():
    tab = _make_tab(TorrentRecord(info_hash="h1", name="X", category=""))
    row = tab._rows["h1"]
    assert tab.table.item(row, CATEGORY_COLUMN).text() == ""

    updated = TorrentRecord(info_hash="h1", name="X", category="Books")
    tab._on_status_updated("h1", updated)

    assert tab.table.item(row, CATEGORY_COLUMN).text() == "Books"


def test_assign_category_action_calls_set_torrent_category_with_chosen_value():
    record = TorrentRecord(info_hash="h1", name="X", category="")
    tab = _make_tab(record)
    tab._session_manager.get_record.return_value = record
    tab._session_manager.list_categories.return_value = ["Movies", "Books"]

    with patch(
        "torrent2000.ui.tabs.downloads_tab.QInputDialog.getItem",
        return_value=("Movies", True),
    ):
        tab._on_assign_category_requested("h1")

    tab._session_manager.set_torrent_category.assert_called_once_with("h1", "Movies")


def test_assign_category_action_does_nothing_when_dialog_is_cancelled():
    record = TorrentRecord(info_hash="h1", name="X", category="")
    tab = _make_tab(record)
    tab._session_manager.get_record.return_value = record
    tab._session_manager.list_categories.return_value = []

    with patch(
        "torrent2000.ui.tabs.downloads_tab.QInputDialog.getItem",
        return_value=("", False),
    ):
        tab._on_assign_category_requested("h1")

    tab._session_manager.set_torrent_category.assert_not_called()


# ------------------------------------------------------------------ magnet link

def test_copy_magnet_writes_uri_to_clipboard_when_available():
    tab = _make_tab(TorrentRecord(info_hash="h1", name="X"))
    tab._session_manager.get_magnet_uri.return_value = "magnet:?xt=urn:btih:abc123"

    tab._on_copy_magnet_requested("h1")

    assert QApplication.clipboard().text() == "magnet:?xt=urn:btih:abc123"


def test_copy_magnet_shows_message_instead_of_clipboard_write_when_unavailable():
    tab = _make_tab(TorrentRecord(info_hash="h1", name="X"))
    tab._session_manager.get_magnet_uri.return_value = None
    QApplication.clipboard().setText("unchanged")

    with patch("torrent2000.ui.tabs.downloads_tab.QMessageBox.information") as mock_info:
        tab._on_copy_magnet_requested("h1")

    mock_info.assert_called_once()
    assert QApplication.clipboard().text() == "unchanged"
