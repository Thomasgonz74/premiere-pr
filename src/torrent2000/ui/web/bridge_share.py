"""QWebChannel bridge backing the Share page -- mirrors ShareTab exactly:
row membership is driven by ShareLimitService.tracked_info_hashes(), NOT by
session_manager.all_records() filtered by state (a seeding torrent added
outside the Partage tab never appears here unless the default share policy
auto-tracks it -- same as native), and the magnet path skips the danger-scan
gate entirely (data is presumed already trusted/on disk, same as native).
"""

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimit, ShareLimitService
from torrent2000.engine.torrent_item import TorrentRecord
from torrent2000.ui.web.dropped_file import save_dropped_bytes_to_temp_file


def _share_row_to_dict(record: TorrentRecord, limit: ShareLimit, elapsed: float, uploaded: int) -> dict:
    return {
        "infoHash": record.info_hash,
        "name": record.name or record.info_hash,
        "uploadRate": record.upload_rate,
        "uploadedBytes": uploaded,
        "elapsedSeconds": elapsed,
        "timeLimitSeconds": limit.time_limit_seconds,
        "dataLimitBytes": limit.data_limit_bytes,
        "ratioLimit": limit.ratio_limit,
        "reached": limit.reached,
        "reachedReason": limit.reached_reason,
        "state": record.state.name,
    }


class ShareBridge(QObject):
    recordUpdated = Signal("QVariantMap")
    recordRemoved = Signal(str)
    started = Signal()

    def __init__(
        self, session_manager: SessionManager, share_limit_service: ShareLimitService, settings, parent=None
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._share_limit_service = share_limit_service
        self._settings = settings
        self._torrent_path: str | None = None
        session_manager.torrent_status_updated.connect(self._on_status_updated)
        session_manager.torrent_removed.connect(self.recordRemoved.emit)
        share_limit_service.limit_reached.connect(lambda ih, _reason: self._push(ih))

    def _row_dict(self, info_hash: str) -> dict | None:
        record = self._session_manager.get_record(info_hash)
        limit = self._share_limit_service.limit_for(info_hash)
        if record is None or limit is None:
            return None
        elapsed, uploaded = self._share_limit_service.progress(info_hash, record)
        return _share_row_to_dict(record, limit, elapsed, uploaded)

    def _push(self, info_hash: str) -> None:
        row = self._row_dict(info_hash)
        if row is not None:
            self.recordUpdated.emit(row)

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        if not self._share_limit_service.is_tracked(info_hash):
            return
        self._push(info_hash)

    @Slot(result="QVariantList")
    def listTorrents(self) -> list:
        rows = []
        for info_hash in self._share_limit_service.tracked_info_hashes():
            row = self._row_dict(info_hash)
            if row is not None:
                rows.append(row)
        return rows

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

    @Slot(result=str)
    def defaultDataDir(self) -> str:
        return self._settings.default_download_dir

    @Slot(str)
    def selectTorrentFile(self, path: str) -> None:
        self._torrent_path = path

    @Slot(str, str, result=str)
    def saveDroppedTorrent(self, filename: str, base64_data: str) -> str:
        return save_dropped_bytes_to_temp_file(filename, base64_data)

    @Slot(str, str, int, int, float, result="QVariantMap")
    def startShare(
        self, data_dir: str, magnet_uri: str, time_limit_hours: int, data_limit_mb: int, ratio_limit: float
    ) -> dict:
        data_dir = (data_dir or "").strip()
        if not data_dir:
            return {"ok": False, "error": "Indiquez le dossier contenant déjà les fichiers."}

        time_limit = time_limit_hours * 3600 or None
        data_limit = data_limit_mb * 1024 * 1024 or None
        ratio = ratio_limit or None

        if self._torrent_path:
            try:
                info_hash = self._session_manager.add_torrent_from_file(self._torrent_path, data_dir)
            except Exception:
                return {"ok": False, "error": "Ce torrent est déjà présent."}
        else:
            magnet_uri = (magnet_uri or "").strip()
            if not magnet_uri:
                return {"ok": False, "error": "Sélectionnez un fichier .torrent ou saisissez un lien magnet."}
            info_hash = self._session_manager.add_torrent_from_magnet(magnet_uri, data_dir)
            self._session_manager.start_after_analysis(info_hash)

        self._share_limit_service.track(info_hash, time_limit, data_limit, ratio_limit=ratio)
        self._torrent_path = None
        self.started.emit()
        return {"ok": True}
