"""Regression tests ensuring failure logs never leak secrets: RSS feed and
item URLs (which frequently carry a private tracker's passkey in the query
string, see engine/rss_feed_service.py) and local watch-folder paths (which
contain the Windows user's profile directory, see
engine/watch_folder_service.py) must never appear verbatim in a log record.
"""

import logging

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.engine.rss_feed_service import RssFeedService, _redact_url
from torrent2000.engine.rss_seen_store import RssSeenStore
from torrent2000.engine.watch_folder_service import WatchFolderService

PASSKEY = "SECRET123"
FEED_URL = f"https://tracker.example/rss?passkey={PASSKEY}"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeSessionManager:
    def add_torrent_from_file(self, path, save_path=None, excluded_indices=None):
        return "fakehash"


def _rss_service(tmp_path):
    settings = Settings()
    settings.default_download_dir = str(tmp_path / "downloads")
    settings.rss_feeds = [RssFeedSubscription(url=FEED_URL, filter_keyword="", enabled=True)]
    seen_store = RssSeenStore(tmp_path / "rss_seen.sqlite3")
    return RssFeedService(_FakeSessionManager(), settings, seen_store)


def test_redact_url_strips_query_string_and_fragment():
    assert _redact_url(f"https://tracker.example/rss?passkey={PASSKEY}") == "https://tracker.example/rss"
    assert _redact_url("https://tracker.example/rss#frag") == "https://tracker.example/rss"
    assert _redact_url("https://tracker.example/rss") == "https://tracker.example/rss"


def test_feed_fetch_failure_never_logs_passkey(tmp_path, caplog):
    service = _rss_service(tmp_path)

    with caplog.at_level(logging.WARNING, logger="torrent2000.engine.rss_feed_service"):
        service._signals.feed_failed.emit(FEED_URL, "connection timed out")

    assert PASSKEY not in caplog.text
    assert "Failed to fetch RSS feed" in caplog.text
    assert "tracker.example/rss" in caplog.text


def test_torrent_download_failure_never_logs_passkey(tmp_path, caplog):
    service = _rss_service(tmp_path)
    item = {
        "title": "Something",
        "link": f"https://tracker.example/dl.torrent?passkey={PASSKEY}",
        "guid": "guid-1",
    }

    with caplog.at_level(logging.WARNING, logger="torrent2000.engine.rss_feed_service"):
        service._signals.torrent_download_failed.emit(FEED_URL, item, "connection reset")

    assert PASSKEY not in caplog.text
    assert "Failed to download .torrent" in caplog.text


def test_magnet_add_failure_never_logs_passkey(tmp_path, caplog):
    class _RaisingSessionManager:
        def add_torrent_from_magnet(self, uri, save_path=None):
            raise RuntimeError("boom")

    settings = Settings()
    settings.default_download_dir = str(tmp_path / "downloads")
    settings.rss_feeds = [RssFeedSubscription(url=FEED_URL, filter_keyword="", enabled=True)]
    seen_store = RssSeenStore(tmp_path / "rss_seen.sqlite3")
    service = RssFeedService(_RaisingSessionManager(), settings, seen_store)

    items = [{"title": "Something", "link": "magnet:?xt=urn:btih:abc", "guid": "guid-2"}]

    with caplog.at_level(logging.ERROR, logger="torrent2000.engine.rss_feed_service"):
        service._signals.feed_fetched.emit(FEED_URL, items)

    assert PASSKEY not in caplog.text
    assert "Failed to add magnet from RSS feed" in caplog.text


def test_watch_folder_add_failure_never_logs_username(tmp_path, caplog):
    watch_dir = tmp_path / "Users" / "fakeuser" / "watch"
    watch_dir.mkdir(parents=True)
    torrent_file = watch_dir / "a.torrent"
    torrent_file.write_bytes(b"fake torrent data")

    class _FailingSessionManager:
        def add_torrent_from_file(self, path, save_path=None, excluded_indices=None):
            raise RuntimeError("boom")

    settings = Settings()
    settings.watch_folder_enabled = True
    settings.watch_folder_path = str(watch_dir)
    settings.default_download_dir = str(tmp_path / "downloads")
    service = WatchFolderService(_FailingSessionManager(), settings)

    with caplog.at_level(logging.ERROR, logger="torrent2000.engine.watch_folder_service"):
        service.scan_now()

    assert "fakeuser" not in caplog.text
    assert "Watch folder: failed to add" in caplog.text
    assert "a.torrent" in caplog.text


def test_watch_folder_move_failure_never_logs_username(tmp_path, caplog, monkeypatch):
    watch_dir = tmp_path / "Users" / "fakeuser" / "watch"
    watch_dir.mkdir(parents=True)
    torrent_file = watch_dir / "a.torrent"
    torrent_file.write_bytes(b"fake torrent data")

    settings = Settings()
    settings.watch_folder_enabled = True
    settings.watch_folder_path = str(watch_dir)
    settings.default_download_dir = str(tmp_path / "downloads")
    service = WatchFolderService(_FakeSessionManager(), settings)

    from pathlib import Path

    def _raise_replace(self, target):
        raise OSError("boom")

    monkeypatch.setattr(Path, "replace", _raise_replace)

    with caplog.at_level(logging.ERROR, logger="torrent2000.engine.watch_folder_service"):
        service.scan_now()

    assert "fakeuser" not in caplog.text
    assert "Watch folder: failed to move" in caplog.text
    assert "a.torrent" in caplog.text
