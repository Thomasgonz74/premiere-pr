"""Regression guard: truncated table cells (long torrent names, RSS feed
URLs/keywords) must expose their full text via QToolTip, since Interactive
columns won't always be dragged wide enough to read them in full."""

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState
from torrent2000.ui.tabs.downloads_tab import DownloadsTab
from torrent2000.ui.tabs.rss_tab import RssTab
from torrent2000.ui.tabs.share_tab import ShareTab

LONG_NAME = "A Very Long Torrent Name That Would Definitely Be Truncated In A Narrow Table Column.iso"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_downloads_tab_sets_tooltip_on_add_row():
    record = TorrentRecord(info_hash="deadbeef1234", name=LONG_NAME, state=TorrentState.DOWNLOADING)
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]
    session_manager.get_record.return_value = record

    tab = DownloadsTab(session_manager)

    row = tab._rows["deadbeef1234"]
    assert tab.table.item(row, 0).toolTip() == LONG_NAME


def test_downloads_tab_keeps_tooltip_in_sync_on_status_update():
    record = TorrentRecord(info_hash="deadbeef1234", name="Short", state=TorrentState.DOWNLOADING)
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]
    session_manager.get_record.return_value = record

    tab = DownloadsTab(session_manager)
    row = tab._rows["deadbeef1234"]
    assert tab.table.item(row, 0).toolTip() == "Short"

    updated = TorrentRecord(info_hash="deadbeef1234", name=LONG_NAME, state=TorrentState.DOWNLOADING)
    tab._on_status_updated("deadbeef1234", updated)

    assert tab.table.item(row, 0).toolTip() == LONG_NAME
    assert tab.table.item(row, 0).text() == LONG_NAME


def test_downloads_tab_falls_back_to_info_hash_prefix_when_unnamed():
    record = TorrentRecord(info_hash="deadbeef1234", name="", state=TorrentState.DOWNLOADING)
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]

    tab = DownloadsTab(session_manager)

    row = tab._rows["deadbeef1234"]
    assert tab.table.item(row, 0).toolTip() == "deadbeef1234"[:12]


def test_share_tab_sets_tooltip_on_add_row():
    record = TorrentRecord(info_hash="abc123", name=LONG_NAME, state=TorrentState.SEEDING)
    session_manager = MagicMock()
    session_manager.get_record.return_value = record

    share_limit_service = MagicMock()
    share_limit_service.tracked_info_hashes.return_value = ["abc123"]
    share_limit_service.limit_for.return_value = None
    share_limit_service.progress.return_value = (0.0, 0)

    tab = ShareTab(session_manager, share_limit_service, Settings())

    row = tab._rows["abc123"]
    assert tab.table.item(row, 0).toolTip() == LONG_NAME


def test_share_tab_keeps_tooltip_in_sync_on_update_row():
    record = TorrentRecord(info_hash="abc123", name="Short", state=TorrentState.SEEDING)
    session_manager = MagicMock()
    session_manager.get_record.return_value = record

    share_limit_service = MagicMock()
    share_limit_service.tracked_info_hashes.return_value = ["abc123"]
    share_limit_service.limit_for.return_value = None
    share_limit_service.progress.return_value = (0.0, 0)

    tab = ShareTab(session_manager, share_limit_service, Settings())
    row = tab._rows["abc123"]
    assert tab.table.item(row, 0).toolTip() == "Short"

    updated = TorrentRecord(info_hash="abc123", name=LONG_NAME, state=TorrentState.SEEDING)
    tab._update_row(row, "abc123", updated)

    assert tab.table.item(row, 0).toolTip() == LONG_NAME
    assert tab.table.item(row, 0).text() == LONG_NAME


def test_rss_tab_sets_tooltips_on_feed_and_keyword_columns():
    long_url = "https://example.com/rss/" + ("a" * 120) + "/feed.xml"
    long_keyword = "a very long filter keyword phrase that would be truncated too"
    settings = Settings()
    settings.rss_feeds = [RssFeedSubscription(url=long_url, filter_keyword=long_keyword, enabled=True)]
    settings.save = MagicMock()

    session_manager = MagicMock()
    feed_service = MagicMock()

    tab = RssTab(session_manager, feed_service, settings)

    assert tab.table.item(0, 0).toolTip() == long_url
    assert tab.table.item(0, 1).toolTip() == long_keyword
