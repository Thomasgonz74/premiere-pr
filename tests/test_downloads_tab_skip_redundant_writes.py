"""Regression test: _on_status_updated must not re-write table cell text
(or tooltip) when the value hasn't actually changed since the last tick,
while still writing through whenever the value genuinely differs."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from torrent2000.engine.torrent_item import TorrentRecord, TorrentState
from torrent2000.ui.tabs.downloads_tab import DownloadsTab

# Columns _on_status_updated writes text to (column 1 is the Tetris progress
# widget, not a text item, so it's excluded here).
_TEXT_COLUMNS = (0, 2, 3, 4, 5, 6)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_tab(record: TorrentRecord) -> DownloadsTab:
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]
    return DownloadsTab(session_manager)


def test_identical_status_update_does_not_rewrite_unchanged_cells():
    record = TorrentRecord(
        info_hash="h1",
        name="X",
        total_size=1000,
        progress=0.5,
        download_rate=0,
        upload_rate=0,
        num_peers=1,
        num_seeds=1,
        state=TorrentState.SEEDING,
    )
    tab = _make_tab(record)
    row = tab._rows["h1"]

    same_record = TorrentRecord(
        info_hash="h1",
        name="X",
        total_size=1000,
        progress=0.5,
        download_rate=0,
        upload_rate=0,
        num_peers=1,
        num_seeds=1,
        state=TorrentState.SEEDING,
    )

    with patch.object(QTableWidgetItem, "setText") as mock_set_text, patch.object(
        QTableWidgetItem, "setToolTip"
    ) as mock_set_tooltip:
        tab._on_status_updated("h1", same_record)

    assert mock_set_text.call_count == 0
    assert mock_set_tooltip.call_count == 0

    # Sanity: the cells still show the correct values (no writes were needed
    # because they already matched).
    assert tab.table.item(row, 3).text() == "0 o/s"
    assert tab.table.item(row, 4).text() == "0 o/s"
    assert tab.table.item(row, 6).text() != ""


def test_changed_download_rate_still_updates_the_corresponding_cell():
    # progress=1.0 keeps the ETA column pinned at "-" regardless of rate, so
    # only the download-rate column's text should actually change here.
    record = TorrentRecord(
        info_hash="h1",
        name="X",
        total_size=1000,
        progress=1.0,
        download_rate=0,
        upload_rate=0,
        num_peers=1,
        num_seeds=1,
        state=TorrentState.SEEDING,
    )
    tab = _make_tab(record)
    row = tab._rows["h1"]

    changed_record = TorrentRecord(
        info_hash="h1",
        name="X",
        total_size=1000,
        progress=1.0,
        download_rate=2048,
        upload_rate=0,
        num_peers=1,
        num_seeds=1,
        state=TorrentState.SEEDING,
    )

    from torrent2000.utils.formatting import human_rate

    with patch.object(QTableWidgetItem, "setText") as mock_set_text:
        tab._on_status_updated("h1", changed_record)

    written_texts = [call.args[0] for call in mock_set_text.call_args_list]
    assert written_texts == [human_rate(2048)]


def test_third_call_after_no_op_call_still_reflects_genuine_change():
    record = TorrentRecord(
        info_hash="h1",
        name="X",
        total_size=1000,
        progress=0.5,
        download_rate=0,
        upload_rate=0,
        num_peers=1,
        num_seeds=1,
        state=TorrentState.SEEDING,
    )
    tab = _make_tab(record)
    row = tab._rows["h1"]

    same_record = TorrentRecord(
        info_hash="h1",
        name="X",
        total_size=1000,
        progress=0.5,
        download_rate=0,
        upload_rate=0,
        num_peers=1,
        num_seeds=1,
        state=TorrentState.SEEDING,
    )
    tab._on_status_updated("h1", same_record)

    changed_record = TorrentRecord(
        info_hash="h1",
        name="X",
        total_size=1000,
        progress=0.5,
        download_rate=500,
        upload_rate=0,
        num_peers=1,
        num_seeds=1,
        state=TorrentState.SEEDING,
    )
    tab._on_status_updated("h1", changed_record)

    from torrent2000.utils.formatting import human_rate

    assert tab.table.item(row, 3).text() == human_rate(500)


def test_health_tooltip_still_updates_when_status_changes():
    # PAUSED is a "health meaningless" state -> blank tooltip.
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.PAUSED)
    tab = _make_tab(record)
    row = tab._rows["h1"]
    assert tab.table.item(row, 6).toolTip() == ""

    healthy_record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING, num_peers=5, num_seeds=5)
    tab._on_status_updated("h1", healthy_record)

    assert tab.table.item(row, 6).toolTip() != ""
