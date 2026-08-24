"""QWebChannel bridge exposing SessionManager's downloads to the web UI.

Full parity with the native DownloadsTab (not just the Phase 0 spike scope):
read the active torrent list, push live updates, pause/resume/remove,
recheck/move storage, plus category/queue-position/sequential-download/
magnet-URI/health -- exactly the same calls and the same health-status logic
DownloadsTab uses today, just re-exposed to JS instead of a QTableWidget.
"""

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
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
        "locked": record.locked,
        "pinned": record.pinned,
        "currentTracker": record.current_tracker,
        "queuePosition": record.queue_position,
        "sequentialDownload": record.sequential_download,
        "deadline": record.deadline,
        "healthStatus": _health_status(record),
    }


# Encryption excluding peers is a real, well-known slowness cause -- but
# there's no rejection counter for it anywhere in the current data model, so
# a "probably encryption" verdict would just be an invented signal. Surfaced
# instead as an explicit disclaimer alongside whatever real causes are found.
_ENCRYPTION_NOT_DETERMINABLE_NOTE = (
    "Le chiffrement qui exclurait certains pairs n'est pas déterminable avec "
    "les données actuelles (aucun compteur de rejets liés au chiffrement "
    "n'existe) : cette cause potentielle n'est donc pas incluse ci-dessus."
)

# Bandwidth is only plausibly "the" bottleneck when the torrent is already
# using most of the configured cap -- below this, the cap isn't what's
# holding it back.
_BANDWIDTH_NEAR_LIMIT_RATIO = 0.9


def _compute_slowness_causes(
    record: TorrentRecord, all_records: list[TorrentRecord], download_limit_kbps: int
) -> list[dict]:
    """Pure function (no QObject) behind DownloadsBridge.explainSlowness --
    the 2 directly-verifiable causes plus 1 inferred one. Only called for a
    torrent already known to be in TorrentState.DOWNLOADING (checked by the
    caller), so no state check is needed here."""
    causes: list[dict] = []

    if record.num_seeds == 0:
        causes.append({
            "code": "no_seeds",
            "text": (
                "Aucun seed n'est actuellement disponible pour ce torrent : "
                "personne ne détient le fichier complet, ce qui limite "
                "fortement la vitesse de téléchargement."
            ),
        })

    error_tracker = next((t for t in record.trackers if t.last_error), None)
    if error_tracker is not None:
        causes.append({
            "code": "tracker_error",
            "text": (
                f"Le tracker {error_tracker.url} renvoie une erreur active "
                f"({error_tracker.last_error}) : moins de pairs peuvent être "
                "découverts via ce tracker."
            ),
        })

    if download_limit_kbps > 0:
        limit_bytes = download_limit_kbps * 1024
        if record.download_rate >= _BANDWIDTH_NEAR_LIMIT_RATIO * limit_bytes:
            others_downloading = any(
                other.info_hash != record.info_hash and other.state == TorrentState.DOWNLOADING
                for other in all_records
            )
            if others_downloading:
                causes.append({
                    "code": "bandwidth_limit",
                    "text": (
                        f"Le débit actuel (~{record.download_rate // 1024} Ko/s) est proche "
                        f"du plafond global configuré ({download_limit_kbps} Ko/s), et "
                        "d'autres torrents téléchargent en même temps : la bande passante "
                        "globale est probablement le facteur limitant."
                    ),
                })

    return causes


class DownloadsBridge(QObject):
    """One instance, constructed after SessionManager and registered on a
    QWebChannel before the page loads. recordUpdated/recordRemoved push
    changes to JS -- the page never polls."""

    recordUpdated = Signal("QVariantMap")
    recordRemoved = Signal(str)

    def __init__(
        self, session_manager: SessionManager, bandwidth_scheduler: BandwidthScheduler, parent=None
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._bandwidth_scheduler = bandwidth_scheduler
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

    @Slot(str)
    def lockTorrent(self, info_hash: str) -> None:
        self._session_manager.lock_torrent(info_hash)

    @Slot(str)
    def unlockTorrent(self, info_hash: str) -> None:
        self._session_manager.unlock_torrent(info_hash)

    @Slot(str)
    def pinTorrent(self, info_hash: str) -> None:
        self._session_manager.pin_torrent(info_hash)

    @Slot(str)
    def unpinTorrent(self, info_hash: str) -> None:
        self._session_manager.unpin_torrent(info_hash)

    @Slot(str, float)
    def setDeadline(self, info_hash: str, timestamp: float) -> None:
        # 0 (falsy in JS, and never a real user-chosen deadline -- 1970) is
        # the "clear" sentinel, avoiding a nullable-parameter QWebChannel
        # slot just for this.
        self._session_manager.set_deadline(info_hash, timestamp if timestamp > 0 else None)

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

    @Slot(str, result="qint64")
    def getAllocatedSize(self, info_hash: str) -> int:
        # A real disk syscall per file -- called on demand when the details
        # panel selects a torrent, not pushed on every status tick like the
        # rest of _record_to_dict.
        return self._session_manager.get_allocated_size(info_hash)

    @Slot(str, result="QVariantMap")
    def explainSlowness(self, info_hash: str) -> dict:
        """On-demand "Pourquoi c'est lent ?" explainer -- never polled, only
        called when the user clicks the button in the details panel. Only
        meaningful for a torrent actively downloading right now."""
        record = self._session_manager.get_record(info_hash)
        if record is None or record.state != TorrentState.DOWNLOADING:
            return {"applicable": False, "causes": [], "note": ""}
        download_limit_kbps = self._bandwidth_scheduler.current_download_limit_kbps()
        causes = _compute_slowness_causes(record, self._session_manager.all_records(), download_limit_kbps)
        return {"applicable": True, "causes": causes, "note": _ENCRYPTION_NOT_DETERMINABLE_NOTE}
