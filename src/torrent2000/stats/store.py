import sqlite3
from pathlib import Path


class StatsStore:
    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS totals ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), "
            "total_downloaded INTEGER NOT NULL DEFAULT 0, "
            "total_uploaded INTEGER NOT NULL DEFAULT 0)"
        )
        self._conn.execute(
            "INSERT OR IGNORE INTO totals (id, total_downloaded, total_uploaded) VALUES (1, 0, 0)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS torrent_counters ("
            "info_hash TEXT PRIMARY KEY, "
            "last_downloaded INTEGER NOT NULL DEFAULT 0, "
            "last_uploaded INTEGER NOT NULL DEFAULT 0)"
        )
        self._conn.commit()

    def get_totals(self) -> tuple[int, int]:
        row = self._conn.execute("SELECT total_downloaded, total_uploaded FROM totals WHERE id = 1").fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def add_totals(self, delta_downloaded: int, delta_uploaded: int) -> None:
        if delta_downloaded <= 0 and delta_uploaded <= 0:
            return
        self._conn.execute(
            "UPDATE totals SET total_downloaded = total_downloaded + ?, "
            "total_uploaded = total_uploaded + ? WHERE id = 1",
            (max(0, delta_downloaded), max(0, delta_uploaded)),
        )
        self._conn.commit()

    def get_torrent_counter(self, info_hash: str) -> tuple[int, int]:
        row = self._conn.execute(
            "SELECT last_downloaded, last_uploaded FROM torrent_counters WHERE info_hash = ?", (info_hash,)
        ).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def set_torrent_counter(self, info_hash: str, last_downloaded: int, last_uploaded: int) -> None:
        self._conn.execute(
            "INSERT INTO torrent_counters (info_hash, last_downloaded, last_uploaded) VALUES (?, ?, ?) "
            "ON CONFLICT(info_hash) DO UPDATE SET last_downloaded = excluded.last_downloaded, "
            "last_uploaded = excluded.last_uploaded",
            (info_hash, last_downloaded, last_uploaded),
        )
        self._conn.commit()

    def apply_flush(
        self,
        total_delta_downloaded: int,
        total_delta_uploaded: int,
        torrent_counters: dict[str, tuple[int, int]],
    ) -> None:
        if total_delta_downloaded > 0 or total_delta_uploaded > 0:
            self._conn.execute(
                "UPDATE totals SET total_downloaded = total_downloaded + ?, "
                "total_uploaded = total_uploaded + ? WHERE id = 1",
                (max(0, total_delta_downloaded), max(0, total_delta_uploaded)),
            )
        for info_hash, (last_downloaded, last_uploaded) in torrent_counters.items():
            self._conn.execute(
                "INSERT INTO torrent_counters (info_hash, last_downloaded, last_uploaded) VALUES (?, ?, ?) "
                "ON CONFLICT(info_hash) DO UPDATE SET last_downloaded = excluded.last_downloaded, "
                "last_uploaded = excluded.last_uploaded",
                (info_hash, last_downloaded, last_uploaded),
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
