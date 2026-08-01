"""Sqlite round-trip tests for the RSS seen-guid dedup store -- no Qt, no
network. See engine/rss_seen_store.py.
"""

from torrent2000.engine.rss_seen_store import RssSeenStore


def test_unseen_guid_reports_false(tmp_path):
    store = RssSeenStore(tmp_path / "rss_seen.sqlite3")
    assert store.is_seen("urn:example:1") is False


def test_marking_seen_makes_is_seen_true(tmp_path):
    store = RssSeenStore(tmp_path / "rss_seen.sqlite3")
    store.mark_seen("urn:example:1", feed_url="https://example.com/feed.xml", title="Example item")
    assert store.is_seen("urn:example:1") is True


def test_marking_seen_twice_does_not_raise(tmp_path):
    store = RssSeenStore(tmp_path / "rss_seen.sqlite3")
    store.mark_seen("urn:example:1")
    store.mark_seen("urn:example:1")  # INSERT OR IGNORE -- must not raise on the duplicate primary key
    assert store.is_seen("urn:example:1") is True


def test_seen_guids_persist_across_store_reopen(tmp_path):
    db_path = tmp_path / "rss_seen.sqlite3"

    store1 = RssSeenStore(db_path)
    store1.mark_seen("urn:example:1")
    store1.close()

    store2 = RssSeenStore(db_path)
    assert store2.is_seen("urn:example:1") is True
    assert store2.is_seen("urn:example:2") is False


def test_different_guids_tracked_independently(tmp_path):
    store = RssSeenStore(tmp_path / "rss_seen.sqlite3")
    store.mark_seen("urn:example:1")
    assert store.is_seen("urn:example:1") is True
    assert store.is_seen("urn:example:2") is False
