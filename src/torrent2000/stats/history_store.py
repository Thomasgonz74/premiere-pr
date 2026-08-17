import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HistoryEntry:
    info_hash: str
    name: str
    total_size: int
    total_downloaded: int
    total_uploaded: int
    finished_at: str  # ISO datetime string
    event: str  # "removed" (torrent taken out of the active list)


class HistoryStore:
    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "info_hash TEXT NOT NULL, "
            "name TEXT NOT NULL, "
            "total_size INTEGER NOT NULL, "
            "total_downloaded INTEGER NOT NULL, "
            "total_uploaded INTEGER NOT NULL, "
            "finished_at TEXT NOT NULL, "
            "event TEXT NOT NULL)"
        )
        self._conn.commit()

    def add_entry(self, entry: HistoryEntry) -> None:
        self._conn.execute(
            "INSERT INTO history "
            "(info_hash, name, total_size, total_downloaded, total_uploaded, finished_at, event) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry.info_hash,
                entry.name,
                entry.total_size,
                entry.total_downloaded,
                entry.total_uploaded,
                entry.finished_at,
                entry.event,
            ),
        )
        self._conn.commit()

    def all_entries(self, limit: int = 200) -> list[HistoryEntry]:
        rows = self._conn.execute(
            "SELECT info_hash, name, total_size, total_downloaded, total_uploaded, finished_at, event "
            "FROM history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [HistoryEntry(*row) for row in rows]

    def clear(self) -> None:
        self._conn.execute("DELETE FROM history")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
