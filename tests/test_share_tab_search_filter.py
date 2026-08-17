import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState
from torrent2000.ui.tabs.share_tab import ShareTab


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_tab(records: dict[str, TorrentRecord]):
    session_manager = MagicMock()
    session_manager.get_record.side_effect = lambda info_hash: records.get(info_hash)

    share_limit_service = MagicMock()
    share_limit_service.tracked_info_hashes.return_value = list(records.keys())
    share_limit_service.limit_for.return_value = None
    share_limit_service.progress.return_value = (0.0, 0)
    share_limit_service.is_tracked.return_value = True

    tab = ShareTab(session_manager, share_limit_service, Settings())
    return tab, session_manager, share_limit_service


def _visible_names(tab):
    return [
        tab.table.item(row, 0).text()
        for row in range(tab.table.rowCount())
        if not tab.table.isRowHidden(row)
    ]


def test_filter_hides_rows_not_matching_torrent_name():
    records = {
        "hash1": TorrentRecord(info_hash="hash1", name="Ubuntu Linux ISO", state=TorrentState.SEEDING),
        "hash2": TorrentRecord(info_hash="hash2", name="Some Music Album", state=TorrentState.SEEDING),
    }
    tab, _, _ = _make_tab(records)

    tab.search_input.setText("linux")

    assert tab.table.isRowHidden(tab._rows["hash1"]) is False
    assert tab.table.isRowHidden(tab._rows["hash2"]) is True
    assert _visible_names(tab) == ["Ubuntu Linux ISO"]


def test_empty_filter_text_shows_all_rows_again():
    records = {
        "hash1": TorrentRecord(info_hash="hash1", name="Ubuntu Linux ISO", state=TorrentState.SEEDING),
        "hash2": TorrentRecord(info_hash="hash2", name="Some Music Album", state=TorrentState.SEEDING),
    }
    tab, _, _ = _make_tab(records)

    tab.search_input.setText("linux")
    tab.search_input.setText("")

    assert tab.table.isRowHidden(tab._rows["hash1"]) is False
    assert tab.table.isRowHidden(tab._rows["hash2"]) is False


def test_filter_is_case_insensitive():
    records = {"hash1": TorrentRecord(info_hash="hash1", name="Ubuntu Linux ISO", state=TorrentState.SEEDING)}
    tab, _, _ = _make_tab(records)

    tab.search_input.setText("UBUNTU")

    assert tab.table.isRowHidden(tab._rows["hash1"]) is False


def test_filter_survives_a_new_row_being_added():
    records = {"hash1": TorrentRecord(info_hash="hash1", name="Ubuntu Linux ISO", state=TorrentState.SEEDING)}
    tab, session_manager, _ = _make_tab(records)

    tab.search_input.setText("linux")

    new_record = TorrentRecord(info_hash="hash2", name="Some Music Album", state=TorrentState.SEEDING)
    records["hash2"] = new_record
    session_manager.get_record.side_effect = lambda info_hash: records.get(info_hash)
    tab._on_status_updated("hash2", new_record)

    assert tab.table.rowCount() == 2
    assert tab.table.isRowHidden(tab._rows["hash1"]) is False
    assert tab.table.isRowHidden(tab._rows["hash2"]) is True
    assert _visible_names(tab) == ["Ubuntu Linux ISO"]


def test_filter_survives_a_row_being_removed():
    records = {
        "hash1": TorrentRecord(info_hash="hash1", name="Ubuntu Linux ISO", state=TorrentState.SEEDING),
        "hash2": TorrentRecord(info_hash="hash2", name="Ubuntu Server ISO", state=TorrentState.SEEDING),
        "hash3": TorrentRecord(info_hash="hash3", name="Some Music Album", state=TorrentState.SEEDING),
    }
    tab, _, _ = _make_tab(records)

    tab.search_input.setText("ubuntu")
    tab._on_torrent_removed("hash1")

    assert tab.table.rowCount() == 2
    assert tab.table.isRowHidden(tab._rows["hash2"]) is False
    assert tab.table.isRowHidden(tab._rows["hash3"]) is True
    assert _visible_names(tab) == ["Ubuntu Server ISO"]
