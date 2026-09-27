"""Coverage for the opt-in torrent search feature (see
engine/torrent_search_service.py): URL templating, per-source RSS search
(never raises), sequential aggregation gated on enabled/{query}, and
TorrentSearchSourceStore's tmp-file + os.replace persistence."""

import json

import pytest

from torrent2000.config.paths import get_torrent_search_sources_path
from torrent2000.engine.torrent_search_service import (
    TorrentSearchSource,
    TorrentSearchSourceStore,
    build_search_url,
    search_all,
    search_source,
)
from torrent2000.engine.url_fetch import FetchError

RSS_SAMPLE = b"""<?xml version="1.0"?>
<rss><channel>
<item><title>Some Linux ISO</title><link>magnet:?xt=urn:btih:abc</link></item>
</channel></rss>"""


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def test_build_search_url_substitutes_and_escapes_query():
    url = build_search_url("https://example.com/rss?q={query}", "linux mint")
    assert url == "https://example.com/rss?q=linux%20mint"


def test_search_source_without_query_placeholder_returns_nothing(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("fetch_url must not be called without a {query} placeholder")

    monkeypatch.setattr("torrent2000.engine.torrent_search_service.fetch_url", _boom)
    source = TorrentSearchSource(name="broken", url_template="https://example.com/rss")
    assert search_source(source, "linux") == []


def test_search_source_parses_rss_and_tags_with_source_name(monkeypatch):
    monkeypatch.setattr(
        "torrent2000.engine.torrent_search_service.fetch_url", lambda *a, **k: RSS_SAMPLE
    )
    source = TorrentSearchSource(name="my-indexer", url_template="https://example.com/rss?q={query}")
    results = search_source(source, "linux")
    assert results == [{"title": "Some Linux ISO", "link": "magnet:?xt=urn:btih:abc", "source": "my-indexer"}]


def test_search_source_returns_empty_on_fetch_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise FetchError("unreachable")

    monkeypatch.setattr("torrent2000.engine.torrent_search_service.fetch_url", _raise)
    source = TorrentSearchSource(name="down", url_template="https://example.com/rss?q={query}")
    assert search_source(source, "linux") == []


def test_search_all_skips_disabled_sources(monkeypatch):
    monkeypatch.setattr(
        "torrent2000.engine.torrent_search_service.fetch_url", lambda *a, **k: RSS_SAMPLE
    )
    sources = [
        TorrentSearchSource(name="on", url_template="https://a.example/rss?q={query}", enabled=True),
        TorrentSearchSource(name="off", url_template="https://b.example/rss?q={query}", enabled=False),
    ]
    results = search_all(sources, "linux")
    assert [r["source"] for r in results] == ["on"]


def test_search_all_aggregates_across_multiple_enabled_sources(monkeypatch):
    monkeypatch.setattr(
        "torrent2000.engine.torrent_search_service.fetch_url", lambda *a, **k: RSS_SAMPLE
    )
    sources = [
        TorrentSearchSource(name="a", url_template="https://a.example/rss?q={query}"),
        TorrentSearchSource(name="b", url_template="https://b.example/rss?q={query}"),
    ]
    results = search_all(sources, "linux")
    assert [r["source"] for r in results] == ["a", "b"]


def test_store_starts_with_zero_default_sources():
    assert TorrentSearchSourceStore().list_sources() == []


def test_store_save_then_list_round_trips():
    store = TorrentSearchSourceStore()
    store.save_source(TorrentSearchSource(name="my-indexer", url_template="https://x/{query}"))
    assert store.list_sources() == [TorrentSearchSource(name="my-indexer", url_template="https://x/{query}")]


def test_store_save_with_same_name_replaces_the_slot():
    store = TorrentSearchSourceStore()
    store.save_source(TorrentSearchSource(name="my-indexer", url_template="https://old/{query}"))
    store.save_source(TorrentSearchSource(name="my-indexer", url_template="https://new/{query}"))
    sources = store.list_sources()
    assert len(sources) == 1
    assert sources[0].url_template == "https://new/{query}"


def test_store_delete_removes_the_source():
    store = TorrentSearchSourceStore()
    store.save_source(TorrentSearchSource(name="my-indexer", url_template="https://x/{query}"))
    store.delete("my-indexer")
    assert store.list_sources() == []


def test_store_persists_across_a_fresh_instance():
    store = TorrentSearchSourceStore()
    store.save_source(TorrentSearchSource(name="my-indexer", url_template="https://x/{query}"))

    reloaded = TorrentSearchSourceStore()
    assert reloaded.list_sources() == [TorrentSearchSource(name="my-indexer", url_template="https://x/{query}")]


def test_missing_persistence_file_starts_empty():
    store = TorrentSearchSourceStore()  # must not raise
    assert store.list_sources() == []


def test_corrupt_persistence_file_does_not_crash_startup():
    path = get_torrent_search_sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not valid json{{{", encoding="utf-8")

    store = TorrentSearchSourceStore()  # must not raise

    assert store.list_sources() == []


def test_persistence_file_with_wrong_shape_entries_are_skipped():
    path = get_torrent_search_sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"name": "ok", "url_template": "https://x/{query}"}, {"bogus": True}]), encoding="utf-8")

    store = TorrentSearchSourceStore()

    assert [s.name for s in store.list_sources()] == ["ok"]
