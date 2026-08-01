"""Small sqlite-backed store of RSS item GUIDs that have already been
auto-downloaded, so restarting the app -- or the next periodic feed check --
doesn't re-add torrents for items it already handled.

Follows the same plain sqlite3 pattern as stats/history_store.py. Only ever
touched from the GUI thread (see engine/rss_feed_service.py): sqlite3
connections are not safe to share across threads, and this store is created
once in app.py and handed to RssFeedService, whose slots all run on the
main thread.
"""

import sqlite3
from datetime import datetime
from pathlib import Path


class RssSeenStore:
    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_items ("
            "guid TEXT PRIMARY KEY, "
            "feed_url TEXT NOT NULL, "
            "title TEXT NOT NULL, "
            "seen_at TEXT NOT NULL)"
        )
        self._conn.commit()

    def is_seen(self, guid: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM seen_items WHERE guid = ?", (guid,)).fetchone()
        return row is not None

    def mark_seen(self, guid: str, feed_url: str = "", title: str = "") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_items (guid, feed_url, title, seen_at) VALUES (?, ?, ?, ?)",
            (guid, feed_url, title, datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
