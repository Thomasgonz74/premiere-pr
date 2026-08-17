"""Integration coverage for RssFeedService's routing-rule resolution (see
engine/routing_rules.py and _on_feed_fetched's save_path computation): the
destination passed to session_manager.add_torrent_from_magnet/the deferred
.torrent download must reflect the first matching "name" rule instead of
always being settings.default_download_dir. Follows the same fake
session-manager + hand-emitted-signal pattern as
test_rss_feed_service_signals.py -- no real network, no real QThreadPool
workers.
"""

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.engine.routing_rules import RoutingRule, RoutingRuleStore
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.rss_seen_store import RssSeenStore


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class FakeSessionManager:
    def __init__(self):
        self.magnet_calls = []
        self.file_calls = []
        self.started_after_analysis = []

    def add_torrent_from_magnet(self, uri, save_path=None):
        self.magnet_calls.append((uri, save_path))
        return "fakehash"

    def add_torrent_from_file(self, path, save_path=None):
        self.file_calls.append((path, save_path))
        return "fakehash"

    def start_after_analysis(self, info_hash):
        self.started_after_analysis.append(info_hash)


def _make_service(tmp_path, feeds):
    settings = Settings()
    settings.default_download_dir = str(tmp_path / "downloads")
    settings.rss_feeds = feeds
    seen_store = RssSeenStore(tmp_path / "rss_seen.sqlite3")
    session_manager = FakeSessionManager()
    service = RssFeedService(session_manager, settings, seen_store)
    return service, session_manager, seen_store, settings


def test_magnet_item_uses_the_routing_rule_destination_when_the_title_matches(tmp_path):
    RoutingRuleStore().save_rule(
        RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux")
    )
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    items = [{"title": "Ubuntu.24.04", "link": "magnet:?xt=urn:btih:abc", "guid": "guid-1"}]
    service._signals.feed_fetched.emit(feed.url, items)

    assert session_manager.magnet_calls == [("magnet:?xt=urn:btih:abc", "D:/linux")]


def test_http_torrent_link_download_uses_the_routing_rule_destination(tmp_path, monkeypatch):
    class _NoOpThreadPool:
        def start(self, runnable, priority=0):
            pass

    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance",
        staticmethod(lambda: _NoOpThreadPool()),
    )

    RoutingRuleStore().save_rule(
        RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux")
    )
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    item = {"title": "Ubuntu.24.04.Server", "link": "https://example.com/x.torrent", "guid": "guid-2"}
    service._signals.feed_fetched.emit(feed.url, [item])

    # Simulate the (no-op'd) download completing -- the runnable is built
    # with the resolved save_path baked in, which is what's checked here.
    downloaded_path = str(tmp_path / "x.torrent")
    service._signals.torrent_downloaded.emit(feed.url, item, downloaded_path, "D:/linux")

    assert session_manager.file_calls == [(downloaded_path, "D:/linux")]


def test_no_matching_rule_falls_back_to_default_download_dir(tmp_path):
    RoutingRuleStore().save_rule(
        RoutingRule(name="linux", pattern="fedora", match_field="name", destination="D:/linux")
    )
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    items = [{"title": "Ubuntu.24.04", "link": "magnet:?xt=urn:btih:abc", "guid": "guid-3"}]
    service._signals.feed_fetched.emit(feed.url, items)

    assert session_manager.magnet_calls == [("magnet:?xt=urn:btih:abc", settings.default_download_dir)]
