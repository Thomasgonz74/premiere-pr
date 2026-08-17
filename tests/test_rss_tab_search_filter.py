import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.ui.tabs.rss_tab import RssTab


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    # RssTab's remove flow calls Settings.save(), which writes to the real
    # app-data config.json unless redirected -- keep tests off the
    # developer's actual Torrent2000 config.
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _make_tab(feeds):
    settings = Settings()
    settings.rss_feeds = list(feeds)
    session_manager = MagicMock()
    rss_feed_service = MagicMock()
    return RssTab(session_manager, rss_feed_service, settings)


def _visible_urls(tab):
    return [
        tab.table.item(row, 0).text()
        for row in range(tab.table.rowCount())
        if not tab.table.isRowHidden(row)
    ]


def test_filter_hides_rows_not_matching_feed_url():
    tab = _make_tab(
        [
            RssFeedSubscription(url="https://example.com/linux-isos.rss"),
            RssFeedSubscription(url="https://example.com/music.rss"),
        ]
    )

    tab.search_input.setText("linux")

    assert tab.table.isRowHidden(0) is False
    assert tab.table.isRowHidden(1) is True
    assert _visible_urls(tab) == ["https://example.com/linux-isos.rss"]


def test_empty_filter_text_shows_all_rows_again():
    tab = _make_tab(
        [
            RssFeedSubscription(url="https://example.com/linux-isos.rss"),
            RssFeedSubscription(url="https://example.com/music.rss"),
        ]
    )

    tab.search_input.setText("linux")
    tab.search_input.setText("")

    assert tab.table.isRowHidden(0) is False
    assert tab.table.isRowHidden(1) is False


def test_filter_is_case_insensitive():
    tab = _make_tab([RssFeedSubscription(url="https://example.com/Linux-ISOs.rss")])

    tab.search_input.setText("LINUX")

    assert tab.table.isRowHidden(0) is False


def test_filter_survives_a_table_refresh():
    feed_to_remove = RssFeedSubscription(url="https://example.com/music.rss")
    tab = _make_tab(
        [
            RssFeedSubscription(url="https://example.com/linux-isos.rss"),
            feed_to_remove,
        ]
    )

    tab.search_input.setText("linux")
    tab._on_remove_clicked(feed_to_remove)  # rebuilds the table via _refresh_table()

    assert tab.table.rowCount() == 1
    assert tab.table.isRowHidden(0) is False
    assert _visible_urls(tab) == ["https://example.com/linux-isos.rss"]
