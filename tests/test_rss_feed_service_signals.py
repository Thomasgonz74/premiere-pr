"""Qt-signal-driven tests for RssFeedService's dedup/filter/add-torrent
wiring, following tests/test_history_service.py's pattern: a fake
session manager stands in for the real (libtorrent-backed) one, and the
worker-thread signals are emitted directly here to simulate what a
successful (or failed) background fetch/download would report -- no real
network access and no QThreadPool workers are ever started.
"""

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.rss_seen_store import RssSeenStore
from torrent2000.engine.url_fetch import FetchError


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    # RssFeedService now also owns a RoutingRuleStore (see
    # engine/routing_rules.py) which reads/writes under the app-data
    # directory -- isolate it so these tests never touch (or create) the
    # real %APPDATA%/Torrent2000 folder on the machine running them.
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


def test_new_matching_magnet_item_is_added_and_marked_seen(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="ubuntu", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    found = []
    service.items_found.connect(lambda url, items: found.append((url, items)))

    items = [{"title": "Ubuntu.24.04", "link": "magnet:?xt=urn:btih:abc", "guid": "guid-1"}]
    service._signals.feed_fetched.emit(feed.url, items)

    assert session_manager.magnet_calls == [("magnet:?xt=urn:btih:abc", settings.default_download_dir)]
    # A magnet is always added paused/awaiting-analysis by SessionManager
    # (so a human can review the file list first) -- an RSS auto-download has
    # no one to review it, so it must be started immediately or it would sit
    # forever without downloading.
    assert session_manager.started_after_analysis == ["fakehash"]
    assert seen_store.is_seen("guid-1") is True
    assert len(found) == 1
    assert found[0][0] == feed.url
    assert found[0][1][0]["guid"] == "guid-1"


def test_non_matching_item_is_not_added_or_marked_seen(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="fedora", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    items = [{"title": "Ubuntu.24.04", "link": "magnet:?xt=urn:btih:abc", "guid": "guid-1"}]
    service._signals.feed_fetched.emit(feed.url, items)

    assert session_manager.magnet_calls == []
    assert seen_store.is_seen("guid-1") is False


def test_already_seen_item_is_skipped_even_if_matching(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])
    seen_store.mark_seen("guid-1")

    items = [{"title": "Anything", "link": "magnet:?xt=urn:btih:abc", "guid": "guid-1"}]
    service._signals.feed_fetched.emit(feed.url, items)

    assert session_manager.magnet_calls == []


def test_disabled_feed_is_ignored_entirely(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=False)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    items = [{"title": "Anything", "link": "magnet:?xt=urn:btih:abc", "guid": "guid-1"}]
    service._signals.feed_fetched.emit(feed.url, items)

    assert session_manager.magnet_calls == []
    assert seen_store.is_seen("guid-1") is False


def test_http_torrent_link_is_marked_seen_immediately_but_added_only_after_download_completes(tmp_path, monkeypatch):
    # _on_feed_fetched's http(s) branch marks the item seen *and* schedules a
    # real QThreadPool worker that would perform a real network download --
    # replace the pool's start() with a no-op so this test exercises the real
    # production slot (mark-seen-before-scheduling) without ever touching the
    # network or leaving a background worker running past the test's return.
    class _NoOpThreadPool:
        def start(self, runnable, priority=0):
            pass

    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance",
        staticmethod(lambda: _NoOpThreadPool()),
    )

    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    item = {"title": "Something", "link": "https://example.com/x.torrent", "guid": "guid-2"}
    service._signals.feed_fetched.emit(feed.url, [item])

    # Marked seen up-front so a second check tick before the download
    # finishes can't queue a duplicate download for the same item.
    assert session_manager.file_calls == []
    assert seen_store.is_seen("guid-2") is True

    # Simulates the download completing -- emitted directly rather than
    # letting a real worker run, per the no-op pool above.
    downloaded_path = str(tmp_path / "x.torrent")
    service._signals.torrent_downloaded.emit(feed.url, item, downloaded_path, settings.default_download_dir)

    assert session_manager.file_calls == [(downloaded_path, settings.default_download_dir)]


def test_feed_fetch_failure_is_relayed_via_feed_check_failed_signal(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    failures = []
    service.feed_check_failed.connect(lambda url, msg: failures.append((url, msg)))

    service._signals.feed_failed.emit(feed.url, "timed out")

    assert failures == [(feed.url, "timed out")]


def test_torrent_download_failure_is_relayed_via_feed_check_failed_signal(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    failures = []
    service.feed_check_failed.connect(lambda url, msg: failures.append((url, msg)))

    item = {"title": "Something", "link": "https://example.com/x.torrent", "guid": "guid-3"}
    service._signals.torrent_download_failed.emit(feed.url, item, "connection reset")

    assert failures == [(feed.url, "connection reset")]
    assert session_manager.file_calls == []


# ---------------------------------------------------------------- proxy passthrough


class _SyncThreadPool:
    """Runs a QRunnable's run() synchronously on start() -- lets a test
    exercise the real production code path (check_now/_on_feed_fetched
    constructing and scheduling a runnable) without any real threading or
    network access, by mocking fetch_url itself below."""

    def start(self, runnable, priority=0):
        runnable.run()


def test_check_now_relays_real_fetch_error_via_feed_check_failed_signal(tmp_path, monkeypatch):
    """Unlike test_feed_fetch_failure_is_relayed_via_feed_check_failed_signal
    above (which hand-emits _signals.feed_failed with a canned message), this
    drives the real _FetchFeedRunnable.run() -- via check_now() and a
    _SyncThreadPool -- so it's the actual try/except around fetch_url() that
    catches FetchError and emits feed_failed, not a stand-in for it."""
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance", staticmethod(lambda: _SyncThreadPool())
    )

    def fake_fetch_url(url, user_agent, timeout_seconds, extra_headers=None, proxy=None):
        raise FetchError("simulated network failure")

    monkeypatch.setattr("torrent2000.engine.rss_feed_service.fetch_url", fake_fetch_url)

    failures = []
    service.feed_check_failed.connect(lambda url, msg: failures.append((url, msg)))

    service.check_now()

    assert failures == [(feed.url, "simulated network failure")]


def test_on_feed_fetched_relays_real_torrent_download_error_via_feed_check_failed_signal(tmp_path, monkeypatch):
    """Unlike test_torrent_download_failure_is_relayed_via_feed_check_failed_signal
    above (which hand-emits _signals.torrent_download_failed with a canned
    message), this drives the real _DownloadTorrentRunnable.run() -- reached
    via _on_feed_fetched scheduling it for an http(s) item link, run
    synchronously by _SyncThreadPool -- so it's the actual try/except around
    fetch_url() that catches FetchError and emits torrent_download_failed,
    not a stand-in for it."""
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])

    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance", staticmethod(lambda: _SyncThreadPool())
    )

    def fake_fetch_url(url, user_agent, timeout_seconds, extra_headers=None, proxy=None):
        raise FetchError("simulated network failure")

    monkeypatch.setattr("torrent2000.engine.rss_feed_service.fetch_url", fake_fetch_url)

    failures = []
    service.feed_check_failed.connect(lambda url, msg: failures.append((url, msg)))

    item = {"title": "Something", "link": "https://example.com/x.torrent", "guid": "guid-real-download-fail"}
    service._signals.feed_fetched.emit(feed.url, [item])

    assert failures == [(feed.url, "simulated network failure")]
    assert session_manager.file_calls == []


def test_check_now_passes_settings_proxy_to_fetch_url(tmp_path, monkeypatch):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])
    settings.proxy.enabled = True
    settings.proxy.proxy_type = "http"
    settings.proxy.host = "proxy.example.com"
    settings.proxy.port = 8080

    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance", staticmethod(lambda: _SyncThreadPool())
    )

    captured_proxies = []

    def fake_fetch_url(url, user_agent, timeout_seconds, extra_headers=None, proxy=None):
        captured_proxies.append(proxy)
        raise FetchError("stop before parsing -- only the proxy kwarg matters here")

    monkeypatch.setattr("torrent2000.engine.rss_feed_service.fetch_url", fake_fetch_url)

    service.check_now()

    assert captured_proxies == [settings.proxy]


def test_on_feed_fetched_passes_settings_proxy_to_fetch_url_for_torrent_download(tmp_path, monkeypatch):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, session_manager, seen_store, settings = _make_service(tmp_path, [feed])
    settings.proxy.enabled = True
    settings.proxy.proxy_type = "http_pw"
    settings.proxy.host = "proxy.example.com"
    settings.proxy.port = 3128
    settings.proxy.username = "alice"
    settings.proxy.password = "s3cret"

    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance", staticmethod(lambda: _SyncThreadPool())
    )

    captured_proxies = []

    def fake_fetch_url(url, user_agent, timeout_seconds, extra_headers=None, proxy=None):
        captured_proxies.append(proxy)
        raise FetchError("stop before writing a file -- only the proxy kwarg matters here")

    monkeypatch.setattr("torrent2000.engine.rss_feed_service.fetch_url", fake_fetch_url)

    item = {"title": "Something", "link": "https://example.com/x.torrent", "guid": "guid-proxy"}
    service._signals.feed_fetched.emit(feed.url, [item])

    assert captured_proxies == [settings.proxy]
