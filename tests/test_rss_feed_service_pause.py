"""Minimal coverage for RssFeedService's set_paused/_paused guard (added for
MemoryPressureGovernor, see engine/memory_pressure_governor.py). Follows
test_rss_feed_service_signals.py's fixture pattern.
"""

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.rss_seen_store import RssSeenStore


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class _NoOpThreadPool:
    def start(self, runnable, priority=0):
        pass


def test_paused_service_skips_check_now(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance",
        staticmethod(lambda: _NoOpThreadPool()),
    )
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    settings = Settings()
    settings.default_download_dir = str(tmp_path / "downloads")
    settings.rss_feeds = [feed]
    seen_store = RssSeenStore(tmp_path / "rss_seen.sqlite3")

    started = []
    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance",
        staticmethod(lambda: type("P", (), {"start": staticmethod(lambda r, priority=0: started.append(r))})()),
    )

    service = RssFeedService(object(), settings, seen_store)
    service.set_paused(True)

    service.check_now()

    assert started == []


def test_unpaused_service_runs_check_now_normally(tmp_path, monkeypatch):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    settings = Settings()
    settings.default_download_dir = str(tmp_path / "downloads")
    settings.rss_feeds = [feed]
    seen_store = RssSeenStore(tmp_path / "rss_seen.sqlite3")

    started = []
    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance",
        staticmethod(lambda: type("P", (), {"start": staticmethod(lambda r, priority=0: started.append(r))})()),
    )

    service = RssFeedService(object(), settings, seen_store)
    service.set_paused(True)
    service.set_paused(False)

    service.check_now()

    assert len(started) == 1
