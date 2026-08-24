"""Logs a torrent's final stats to HistoryStore when it's taken out of the
active list, so what was downloaded/shared stays on record even after
removal (SessionManager already pops its live record before the
torrent_removed signal fires, so status updates are cached here first)."""

from datetime import datetime

from PySide6.QtCore import QObject, Signal

from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord
from torrent2000.stats.history_store import HistoryEntry, HistoryStore


class HistoryService(QObject):
    entry_added = Signal()

    def __init__(self, store: HistoryStore, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._last_known: dict[str, TorrentRecord] = {}
        # Set by MemoryPressureGovernor (see engine/memory_pressure_governor.py)
        # while system memory usage is over its configured threshold -- skips
        # the disk write below (but still drops the popped record, so
        # _last_known can't grow unbounded while paused either).
        self._paused = False
        session_manager.torrent_status_updated.connect(self._on_status_updated)
        session_manager.torrent_removed.connect(self._on_torrent_removed)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        self._last_known[info_hash] = record

    def _on_torrent_removed(self, info_hash: str) -> None:
        record = self._last_known.pop(info_hash, None)
        if record is None or self._paused:
            return
        self._store.add_entry(
            HistoryEntry(
                info_hash=record.info_hash,
                name=record.name or info_hash[:12],
                total_size=record.total_size,
                total_downloaded=record.all_time_downloaded,
                total_uploaded=record.all_time_uploaded,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                event="removed",
            )
        )
        self.entry_added.emit()

    def all_entries(self, limit: int = 200) -> list[HistoryEntry]:
        return self._store.all_entries(limit)

    def clear(self) -> None:
        self._store.clear()
        self.entry_added.emit()
