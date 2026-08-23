"""QWebChannel bridge exposing SessionManager's downloads to the web UI.

Full parity with the native DownloadsTab (not just the Phase 0 spike scope):
read the active torrent list, push live updates, pause/resume/remove,
recheck/move storage, plus category/queue-position/sequential-download/
magnet-URI/health -- exactly the same calls and the same health-status logic
DownloadsTab uses today, just re-exposed to JS instead of a QTableWidget.
"""

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState

# States where a health verdict wouldn't mean anything yet -- mirrors
# downloads_tab.py's _HEALTH_MEANINGLESS_STATES exactly.
_HEALTH_MEANINGLESS_STATES = {
    TorrentState.PAUSED,
    TorrentState.AWAITING_ANALYSIS,
    TorrentState.CHECKING_METADATA,
    TorrentState.QUEUED,
}


def _health_status(record: TorrentRecord) -> str:
    """Ported verbatim from downloads_tab.py's _health_status(): "critical"
    (errored, or no seeds while the tracker is erroring), "warning" (no
    peers or no seeds), "healthy", or "" when health isn't meaningful yet."""
    if record.state in _HEALTH_MEANINGLESS_STATES:
        return ""
    if record.state == TorrentState.ERROR:
        return "critical"
    has_tracker_error = any(tracker.last_error for tracker in record.trackers)
    if record.num_seeds == 0 and has_tracker_error:
        return "critical"
    if record.num_seeds == 0 or record.num_peers == 0:
        return "warning"
    return "healthy"


def _record_to_dict(record: TorrentRecord) -> dict:
    return {
        "infoHash": record.info_hash,
        "name": record.name or record.info_hash,
        "progress": record.progress,
        "state": record.state.name,
        "downloadRate": record.download_rate,
        "uploadRate": record.upload_rate,
        "numPeers": record.num_peers,
        "numSeeds": record.num_seeds,
        "totalSize": record.total_size,
        "category": record.category,
        "isPrivate": record.is_private,
        "currentTracker": record.current_tracker,
        "queuePosition": record.queue_position,
        "sequentialDownload": record.sequential_download,
        "healthStatus": _health_status(record),
    }


class DownloadsBridge(QObject):
    """One instance, constructed after SessionManager and registered on a
    QWebChannel before the page loads. recordUpdated/recordRemoved push
    changes to JS -- the page never polls."""

    recordUpdated = Signal("QVariantMap")
    recordRemoved = Signal(str)

    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        session_manager.torrent_added.connect(self._on_added_or_updated)
        session_manager.torrent_status_updated.connect(self._on_status_updated)
        session_manager.torrent_removed.connect(self.recordRemoved.emit)

    def _on_added_or_updated(self, info_hash: str) -> None:
        record = self._session_manager.get_record(info_hash)
        if record is not None:
            self.recordUpdated.emit(_record_to_dict(record))

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        self.recordUpdated.emit(_record_to_dict(record))

    @Slot(result="QVariantList")
    def listTorrents(self) -> list:
        """Called once by the page on load, so it doesn't have to wait for
        the next status tick to see torrents already present at startup."""
        return [_record_to_dict(r) for r in self._session_manager.all_records()]

    @Slot(str)
    def pauseTorrent(self, info_hash: str) -> None:
        self._session_manager.pause_torrent(info_hash)

    @Slot(str)
    def resumeTorrent(self, info_hash: str) -> None:
        self._session_manager.resume_torrent(info_hash)

    @Slot(str, bool)
    def removeTorrent(self, info_hash: str, delete_files: bool) -> None:
        self._session_manager.remove_torrent(info_hash, delete_files=delete_files)

    @Slot(str)
    def recheckTorrent(self, info_hash: str) -> None:
        self._session_manager.recheck_torrent(info_hash)

    @Slot(str, str)
    def moveStorage(self, info_hash: str, new_path: str) -> None:
        if new_path:
            self._session_manager.move_storage(info_hash, new_path)

    @Slot(str, str)
    def setCategory(self, info_hash: str, category: str) -> None:
        self._session_manager.set_torrent_category(info_hash, category.strip())

    @Slot(result="QVariantList")
    def listCategories(self) -> list:
        return self._session_manager.list_categories()

    @Slot(str)
    def moveQueueUp(self, info_hash: str) -> None:
        self._session_manager.move_queue_up(info_hash)

    @Slot(str)
    def moveQueueDown(self, info_hash: str) -> None:
        self._session_manager.move_queue_down(info_hash)

    @Slot(str, bool)
    def setSequentialDownload(self, info_hash: str, enabled: bool) -> None:
        self._session_manager.set_sequential_download(info_hash, enabled)

    @Slot(str, result=str)
    def getMagnetUri(self, info_hash: str) -> str:
        return self._session_manager.get_magnet_uri(info_hash) or ""
