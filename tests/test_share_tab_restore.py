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


def test_tab_repopulates_from_already_tracked_torrents_on_construction():
    record = TorrentRecord(info_hash="abc123", name="Restored Share", save_path="C:\\x", state=TorrentState.SEEDING)
    session_manager = MagicMock()
    session_manager.get_record.return_value = record

    share_limit_service = MagicMock()
    share_limit_service.tracked_info_hashes.return_value = ["abc123"]
    share_limit_service.limit_for.return_value = None
    share_limit_service.progress.return_value = (0.0, 0)

    tab = ShareTab(session_manager, share_limit_service, Settings())

    assert "abc123" in tab._rows
    assert tab.table.rowCount() == 1
    assert tab.table.item(tab._rows["abc123"], 0).text() == "Restored Share"


def test_tab_skips_a_tracked_hash_whose_torrent_no_longer_exists():
    session_manager = MagicMock()
    session_manager.get_record.return_value = None  # torrent was removed from libtorrent but limit entry wasn't cleaned up somehow

    share_limit_service = MagicMock()
    share_limit_service.tracked_info_hashes.return_value = ["gone"]

    tab = ShareTab(session_manager, share_limit_service, Settings())

    assert tab.table.rowCount() == 0


def test_tab_stays_empty_when_nothing_was_tracked():
    session_manager = MagicMock()
    share_limit_service = MagicMock()
    share_limit_service.tracked_info_hashes.return_value = []

    tab = ShareTab(session_manager, share_limit_service, Settings())

    assert tab.table.rowCount() == 0
