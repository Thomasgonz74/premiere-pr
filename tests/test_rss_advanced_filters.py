"""Coverage for the RSS advanced filters (catalogue idea): regex include/
exclude, resolution min/max, and latest-episode-only batching (see
engine/rss_feed_service.py::matches_advanced_filters and _on_feed_fetched)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.engine.rss_feed_service import (
    RssFeedService,
    _title_episode,
    _title_resolution,
    matches_advanced_filters,
)
from torrent2000.engine.rss_seen_store import RssSeenStore


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


# --------------------------------------------------------------- pure helpers


def test_title_resolution_extracts_p_suffixed_marker():
    assert _title_resolution("Show.S01E02.1080p.WEB") == 1080
    assert _title_resolution("Show.S01E02.720p") == 720
    assert _title_resolution("Show with no resolution marker") is None


def test_matches_advanced_filters_regex_include():
    feed = RssFeedSubscription(regex_include=r"1080p")
    assert matches_advanced_filters("Show.1080p.WEB", feed) is True
    assert matches_advanced_filters("Show.720p.WEB", feed) is False


def test_matches_advanced_filters_regex_exclude():
    feed = RssFeedSubscription(regex_exclude=r"CAM|TS")
    assert matches_advanced_filters("Show.1080p.WEB", feed) is True
    assert matches_advanced_filters("Show.CAM.Rip", feed) is False


def test_matches_advanced_filters_resolution_range():
    feed = RssFeedSubscription(resolution_min=720, resolution_max=1080)
    assert matches_advanced_filters("Show.1080p", feed) is True
    assert matches_advanced_filters("Show.480p", feed) is False
    assert matches_advanced_filters("Show.2160p", feed) is False


def test_matches_advanced_filters_no_resolution_marker_never_fails_resolution_filter():
    feed = RssFeedSubscription(resolution_min=720)
    assert matches_advanced_filters("Show with no resolution tag", feed) is True


def test_matches_advanced_filters_all_unset_matches_everything():
    feed = RssFeedSubscription()
    assert matches_advanced_filters("Anything at all", feed) is True


# --------------------------------------------------------------- integration


class FakeSessionManager(QObject):
    metadata_received = Signal(str)

    def add_torrent_from_magnet(self, uri, save_path=None):
        return "fakehash"

    def add_torrent_from_file(self, path, save_path=None, excluded_indices=None):
        return "fakehash"

    def start_after_analysis(self, info_hash):
        pass


def _make_service(tmp_path, feed):
    settings = Settings()
    settings.default_download_dir = str(tmp_path / "downloads")
    settings.rss_feeds = [feed]
    seen_store = RssSeenStore(tmp_path / "rss_seen.sqlite3")
    session_manager = FakeSessionManager()
    service = RssFeedService(session_manager, settings, seen_store)
    return service, seen_store


def test_latest_episode_only_keeps_just_the_highest_numbered_item_and_seeds_the_rest(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True, latest_episode_only=True)
    service, seen_store = _make_service(tmp_path, feed)

    found = []
    service.items_found.connect(lambda url, items: found.extend(items))

    items = [
        {"title": "Show.S01E01", "link": "magnet:?xt=urn:btih:aaa", "guid": "g1"},
        {"title": "Show.S01E03", "link": "magnet:?xt=urn:btih:ccc", "guid": "g3"},
        {"title": "Show.S01E02", "link": "magnet:?xt=urn:btih:bbb", "guid": "g2"},
    ]
    service._signals.feed_fetched.emit(feed.url, items)

    assert len(found) == 1
    assert found[0]["guid"] == "g3"
    # The other two are marked seen (never retried) even though never added.
    assert seen_store.is_seen("g1") is True
    assert seen_store.is_seen("g2") is True


def test_advanced_filter_rejects_non_matching_items_before_add(tmp_path):
    feed = RssFeedSubscription(
        url="https://example.com/feed.xml", filter_keyword="", enabled=True, regex_include=r"1080p"
    )
    service, seen_store = _make_service(tmp_path, feed)

    found = []
    service.items_found.connect(lambda url, items: found.extend(items))

    items = [{"title": "Show.720p", "link": "magnet:?xt=urn:btih:aaa", "guid": "g1"}]
    service._signals.feed_fetched.emit(feed.url, items)

    assert found == []
    assert seen_store.is_seen("g1") is False  # rejected before the seen-store is ever touched


def test_bridge_update_feed_filters_persists_the_new_fields(tmp_path):
    from torrent2000.ui.web.bridge_rss import RssBridge

    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, _seen_store = _make_service(tmp_path, feed)
    bridge = RssBridge(service._session_manager, service, service._settings)

    bridge.updateFeedFilters(
        feed.url,
        {
            "regexInclude": "1080p",
            "regexExclude": "CAM",
            "resolutionMin": 720,
            "resolutionMax": 2160,
            "latestEpisodeOnly": True,
        },
    )

    updated = service._settings.rss_feeds[0]
    assert updated.regex_include == "1080p"
    assert updated.regex_exclude == "CAM"
    assert updated.resolution_min == 720
    assert updated.resolution_max == 2160
    assert updated.latest_episode_only is True


def test_latest_episode_only_ranks_by_season_episode_not_codec_tags(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True, latest_episode_only=True)
    service, seen_store = _make_service(tmp_path, feed)

    found = []
    service.items_found.connect(lambda url, items: found.extend(items))

    items = [
        {"title": "Show.S01E05.720p.WEB.x264-GRP", "link": "magnet:?xt=urn:btih:e05", "guid": "g5"},
        {"title": "Show.S01E07.1080p.WEB.H.265-GRP", "link": "magnet:?xt=urn:btih:e07", "guid": "g7"},
        {"title": "Show.S01E08.720p.HDTV.AAC2.0", "link": "magnet:?xt=urn:btih:e08", "guid": "g8"},
        {"title": "Show.Special.720p", "link": "magnet:?xt=urn:btih:sp", "guid": "gs"},
    ]
    service._signals.feed_fetched.emit(feed.url, items)

    # The newest episode wins, not the one with the biggest codec number;
    # an item with no episode marker is not ranked, so not dropped either.
    assert [item["guid"] for item in found] == ["g8", "gs"]
    assert seen_store.is_seen("g5") is True
    assert seen_store.is_seen("g7") is True


def test_invalid_filter_regex_is_refused_on_save_and_skipped_by_the_check(tmp_path):
    from torrent2000.ui.web.bridge_rss import RssBridge

    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    service, seen_store = _make_service(tmp_path, feed)
    bridge = RssBridge(service._session_manager, service, service._settings)

    result = bridge.updateFeedFilters(feed.url, {"regexInclude": "*1080p*"})
    assert result["ok"] is False and "*1080p*" in result["error"]
    assert feed.regex_include == ""

    # A bad pattern already in config.json (edited by hand, or saved before
    # the check above existed): the check reports it instead of raising.
    feed.regex_include = "(1080p"
    failed, found = [], []
    service.feed_check_failed.connect(lambda url, message: failed.append(message))
    service.items_found.connect(lambda url, items: found.extend(items))
    service._signals.feed_fetched.emit(feed.url, [{"title": "Show.1080p", "link": "magnet:?xt=urn:btih:a", "guid": "g1"}])

    assert len(failed) == 1 and "(1080p" in failed[0]
    assert found == []
    assert seen_store.is_seen("g1") is False  # downloads once the pattern is fixed


def test_title_episode_reads_real_world_release_names():
    cases = {
        "The.Last.of.Us.S02E07.1080p.WEB.H264-SuccessfulCrab": (("the", "last", "of", "us"), (2, 7)),
        "House.of.the.Dragon.S02E08.2160p.MAX.WEB-DL.DDP5.1.Atmos.DV.HDR.H.265-FLUX": (
            ("house", "of", "the", "dragon"),
            (2, 8),
        ),
        "Show.Name.Season.2.Episode.3.720p": (("show", "name"), (2, 3)),
        "Doctor Who 2x05 HDTV XviD": (("doctor", "who"), (2, 5)),
        "[SubsPlease] Frieren - 28 (1080p) [ABCD1234].mkv": (("frieren",), (0, 28)),
        "One.Piece.Episode.1100.VOSTFR.1080p": (("one", "piece"), (0, 1100)),
        "The.Daily.Show.2026.11.22.Guest.720p.WEB.h264-EDITH": (("the", "daily", "show"), (2026, 11, 22)),
        "Jimmy.Kimmel.Live.2026-11-21.720p": (("jimmy", "kimmel", "live"), (2026, 11, 21)),
        "Le.Journal.22.11.2026.FRENCH.720p": (("le", "journal"), (2026, 11, 22)),
        # A season pack comes after every episode of its season.
        "Shogun.2024.S01.1080p.WEB.H.265": (("shogun", "2024"), (1, 10**6)),
        # Ambiguous date (5 October or 10 May?), and resolution/codec/audio
        # numbers only: no marker at all.
        "Le.Journal.10.05.2026.FRENCH": None,
        "Show.Christmas.Special.720p.HDTV.x264": None,
        "Show.1080p.WEB.x264.10bit.DDP5.1": None,
        "Show - 1080p": None,
        "Show - 5.1": None,
    }
    for title, expected in cases.items():
        assert _title_episode(title) == expected, title


def test_latest_episode_only_takes_the_newest_item_of_each_show(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True, latest_episode_only=True)
    service, seen_store = _make_service(tmp_path, feed)
    found = []
    service.items_found.connect(lambda url, items: found.extend(items))

    titles = [  # feed order: newest first
        "The.Daily.Show.2026.11.22.Guest.720p.WEB.h264-EDITH",
        "Show.Christmas.Special.720p.HDTV.x264",
        "The.Daily.Show.2026.11.21.Guest.720p.WEB.h264-EDITH",
        "Show.S01E09.1080p.WEB.H.265-GRP",
        "Show.Behind.The.Scenes.720p.HDTV.x264",
        "Show.S01.1080p.WEB.H.265-GRP",
        "Other.Show.S03E02.720p.WEB.x264-GRP",
        "The.Daily.Show.2026.11.20.Guest.720p.WEB.h264-EDITH",
        "Other.Show.S03E01.1080p.WEB.x264-GRP",
    ]
    items = [{"title": t, "link": f"magnet:?xt=urn:btih:{i:040x}", "guid": f"g{i}"} for i, t in enumerate(titles)]
    service._signals.feed_fetched.emit(feed.url, items)

    # One per show, plus the show's newest item with no episode marker.
    assert sorted(item["title"] for item in found) == sorted(
        [titles[0], titles[1], titles[5], titles[6]]
    )
    assert all(seen_store.is_seen(item["guid"]) for item in items)


def test_latest_episode_only_marks_older_items_seen_only_once_the_newest_is_added(tmp_path, monkeypatch):
    started = []

    class _RecordingThreadPool:
        def start(self, runnable, priority=0):
            started.append(runnable)

    monkeypatch.setattr(
        "torrent2000.engine.rss_feed_service.QThreadPool.globalInstance", staticmethod(lambda: _RecordingThreadPool())
    )
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True, latest_episode_only=True)
    service, seen_store = _make_service(tmp_path, feed)
    newest = {"title": "Show.S01E08.720p.HDTV.AAC2.0", "link": "https://example.com/e08.torrent", "guid": "g8"}
    older = {"title": "Show.S01E07.1080p.WEB.H.265-GRP", "link": "magnet:?xt=urn:btih:e07", "guid": "g7"}

    service._signals.feed_fetched.emit(feed.url, [newest, older])
    service._signals.torrent_download_failed.emit(feed.url, newest, "connection reset")
    assert not seen_store.is_seen("g8") and not seen_store.is_seen("g7")

    service._signals.feed_fetched.emit(feed.url, [newest, older])
    assert len(started) == 2  # the newest again, never the older one meanwhile
    service._signals.torrent_downloaded.emit(feed.url, newest, str(tmp_path / "e08.torrent"), "")
    assert seen_store.is_seen("g8") and seen_store.is_seen("g7")

    # A magnet whose add fails is not marked seen, nor are the items skipped for it.
    monkeypatch.setattr(service._session_manager, "add_torrent_from_magnet", lambda *a: 1 / 0)
    items = [
        {"title": "Show.S01E10.720p", "link": "magnet:?xt=urn:btih:e10", "guid": "g10"},
        {"title": "Show.S01E09.720p", "link": "magnet:?xt=urn:btih:e09", "guid": "g9"},
    ]
    service._signals.feed_fetched.emit(feed.url, items)
    assert not seen_store.is_seen("g10") and not seen_store.is_seen("g9")


def test_latest_episode_only_skips_a_new_copy_of_an_episode_already_taken(tmp_path):
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True, latest_episode_only=True)
    service, seen_store = _make_service(tmp_path, feed)
    found = []
    service.items_found.connect(lambda url, items: found.extend(items))
    taken = {"title": "Show.S01E05.720p.WEB.x264-GRP", "link": "magnet:?xt=urn:btih:a", "guid": "g720"}
    service._signals.feed_fetched.emit(feed.url, [taken])

    copy = {"title": "Show.S01E05.1080p.WEB.x264-GRP", "link": "magnet:?xt=urn:btih:b", "guid": "g1080"}
    service._signals.feed_fetched.emit(feed.url, [copy, taken])

    assert [item["guid"] for item in found] == ["g720"]
    assert seen_store.is_seen("g1080") is True
