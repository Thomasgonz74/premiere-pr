"""QWebChannel bridge backing the Stats group of the Profile page --
LevelingSection + HistorySection. Both are read-only display (no settings to
save); the only mutating actions are clearing history and exporting it to
CSV, mirroring HistorySection's own QMessageBox.question confirm (done
client-side in JS -- there's no native dialog equivalent to reuse here) and
_on_export_csv_clicked (raw byte counts in the CSV, not human_size()
strings) exactly.
"""

import csv

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.history_store import HistoryEntry
from torrent2000.stats.models import StatsSnapshot
from torrent2000.stats.service import StatsService

_HISTORY_CSV_COLUMNS = ["info_hash", "name", "total_size", "total_downloaded", "total_uploaded", "finished_at", "event"]


def _snapshot_to_dict(snap: StatsSnapshot) -> dict:
    return {
        "totalDownloaded": snap.total_downloaded,
        "totalUploaded": snap.total_uploaded,
        "level": snap.level,
        "progressToNext": snap.progress_to_next,
        "currentThreshold": snap.current_threshold,
        "nextThreshold": snap.next_threshold,
    }


def _entry_to_dict(entry: HistoryEntry) -> dict:
    return {
        "infoHash": entry.info_hash,
        "name": entry.name,
        "totalSize": entry.total_size,
        "totalDownloaded": entry.total_downloaded,
        "totalUploaded": entry.total_uploaded,
        "finishedAt": entry.finished_at,
        "event": entry.event,
    }


class ProfileStatsBridge(QObject):
    snapshotUpdated = Signal("QVariantMap")  # StatsSnapshot, converted to a dict
    historyChanged = Signal()  # full refresh, matches native HistorySection.refresh()

    def __init__(self, stats_service: StatsService, history_service: HistoryService, parent=None) -> None:
        super().__init__(parent)
        self._stats_service = stats_service
        self._history_service = history_service
        stats_service.snapshot_updated.connect(self._on_snapshot_updated)
        history_service.entry_added.connect(self.historyChanged.emit)

    def _on_snapshot_updated(self, snap: StatsSnapshot) -> None:
        self.snapshotUpdated.emit(_snapshot_to_dict(snap))

    @Slot(result="QVariantMap")
    def getStatsSnapshot(self) -> dict:
        return _snapshot_to_dict(self._stats_service.current_snapshot())

    @Slot(result="QVariantList")
    def getHistoryEntries(self) -> list:
        return [_entry_to_dict(entry) for entry in self._history_service.all_entries(limit=200)]

    @Slot(result="QVariantMap")
    def clearHistory(self) -> dict:
        self._history_service.clear()  # emits entry_added -> historyChanged, JS refreshes from that
        return {"ok": True}

    @Slot(str, result="QVariantMap")
    def exportHistoryCsv(self, path: str) -> dict:
        if not path:
            return {"ok": False}
        entries = self._history_service.all_entries(limit=200)
        try:
            # Raw byte counts (not human_size() strings) -- matches native
            # _on_export_csv_clicked: a CSV export is meant to be re-parsed
            # by another tool, so it carries numbers, not formatted text.
            with open(path, "w", newline="", encoding="utf-8") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(_HISTORY_CSV_COLUMNS)
                for entry in entries:
                    writer.writerow(
                        [
                            entry.info_hash,
                            entry.name,
                            entry.total_size,
                            entry.total_downloaded,
                            entry.total_uploaded,
                            entry.finished_at,
                            entry.event,
                        ]
                    )
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}
