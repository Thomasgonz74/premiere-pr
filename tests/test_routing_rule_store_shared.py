"""A routing rule added in the Profile tab during the session must reach the
watch folder and RSS at once: the app hands both services the one
RoutingRuleStore its rule editor writes to (RoutingRuleStore reads
routing_rules.json only when built, so a private store stays stale until a
restart)."""

import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.engine.routing_rules import RoutingRule, RoutingRuleStore
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.rss_seen_store import RssSeenStore
from torrent2000.engine.watch_folder_service import WatchFolderService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path_factory.mktemp("data_dir")))


class _NoOpSignal:
    def connect(self, slot):
        pass


class FakeSessionManager:
    metadata_received = _NoOpSignal()

    def __init__(self):
        self.added: list[tuple[str, str]] = []
        self.matched: dict[str, str] = {}

    def add_torrent_from_file(self, path, save_path=None, excluded_indices=None):
        self.added.append((Path(path).name, save_path))
        return "filehash"

    def add_torrent_from_magnet(self, uri, save_path=None):
        self.added.append((uri, save_path))
        return "magnethash"

    def set_matched_rule_name(self, info_hash, name):
        self.matched[info_hash] = name


def test_a_rule_added_after_startup_routes_watch_folder_and_rss_items(tmp_path):
    calls = {
        node.func.id: [ast.unparse(arg) for arg in node.args]
        for node in ast.walk(ast.parse((ROOT / "run_web_spike.py").read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "routing_rule_store" in calls["WatchFolderService"]
    assert "routing_rule_store" in calls["RssFeedService"]

    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    settings = Settings()
    settings.default_download_dir = "C:/downloads"
    settings.watch_folder_enabled = True
    settings.watch_folder_path = str(watch_dir)
    feed = RssFeedSubscription(url="https://example.com/feed.xml", filter_keyword="", enabled=True)
    settings.rss_feeds = [feed]
    session_manager = FakeSessionManager()
    shared = RoutingRuleStore()
    watch = WatchFolderService(session_manager, settings, shared)
    rss = RssFeedService(session_manager, settings, RssSeenStore(tmp_path / "rss_seen.sqlite3"), shared)

    shared.save_rule(RoutingRule(name="beta", pattern="Routed", match_field="name", destination="D:/routed"))
    (watch_dir / "Routed.Beta.mkv.torrent").write_bytes(b"fake torrent data")
    watch.scan_now()
    rss._signals.feed_fetched.emit(feed.url, [{"title": "Routed.Gamma", "link": "magnet:?xt=urn:btih:g", "guid": "g"}])

    assert session_manager.added == [
        ("Routed.Beta.mkv.torrent", "D:/routed"),
        ("magnet:?xt=urn:btih:g", "D:/routed"),
    ]
    assert session_manager.matched == {"filehash": "beta", "magnethash": "beta"}
