from PySide6.QtCore import QObject, QTimer, Signal

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord
from torrent2000.stats.leveling import score_factors_for, snapshot
from torrent2000.stats.models import StatsSnapshot
from torrent2000.stats.store import StatsStore

FLUSH_INTERVAL_MS = 10_000


class StatsService(QObject):
    """Accumulates cumulative downloaded/uploaded bytes across restarts and
    re-added torrents, by tracking a delta against each torrent's last-seen
    all-time counters rather than trusting any single handle's lifetime
    totals (which reset to 0 if a torrent is removed and re-added)."""

    snapshot_updated = Signal(object)  # StatsSnapshot

    def __init__(
        self, store: StatsStore, session_manager: SessionManager, settings: Settings | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._session_manager = session_manager
        self._settings = settings
        self._current: dict[str, tuple[int, int]] = {}
        self._last_seen: dict[str, tuple[int, int]] = {}

        session_manager.torrent_status_updated.connect(self._on_status_updated)
        session_manager.torrent_removed.connect(self._on_torrent_removed)

        self._flush_timer = QTimer(self)
        self._flush_timer.timeout.connect(self.flush)
        self._flush_timer.start(FLUSH_INTERVAL_MS)

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        self._current[info_hash] = (record.all_time_downloaded, record.all_time_uploaded)

    def _on_torrent_removed(self, info_hash: str) -> None:
        self._flush_one(info_hash)
        self._current.pop(info_hash, None)

    def _last_seen_for(self, info_hash: str) -> tuple[int, int]:
        if info_hash not in self._last_seen:
            self._last_seen[info_hash] = self._store.get_torrent_counter(info_hash)
        return self._last_seen[info_hash]

    def _flush_one(self, info_hash: str) -> None:
        current = self._current.get(info_hash)
        if current is None:
            return
        current_down, current_up = current
        last_down, last_up = self._last_seen_for(info_hash)
        delta_down = max(0, current_down - last_down)
        delta_up = max(0, current_up - last_up)
        if delta_down or delta_up:
            self._store.add_totals(delta_down, delta_up)
        self._store.set_torrent_counter(info_hash, current_down, current_up)
        self._last_seen[info_hash] = (current_down, current_up)

    def flush(self) -> None:
        total_delta_down = 0
        total_delta_up = 0
        torrent_counters: dict[str, tuple[int, int]] = {}
        for info_hash in list(self._current.keys()):
            current_down, current_up = self._current[info_hash]
            last_down, last_up = self._last_seen_for(info_hash)
            total_delta_down += max(0, current_down - last_down)
            total_delta_up += max(0, current_up - last_up)
            torrent_counters[info_hash] = (current_down, current_up)
            self._last_seen[info_hash] = (current_down, current_up)
        if torrent_counters:
            self._store.apply_flush(total_delta_down, total_delta_up, torrent_counters)
        self.snapshot_updated.emit(self.current_snapshot())

    def current_snapshot(self) -> StatsSnapshot:
        total_down, total_up = self._store.get_totals()
        theme_id = self._settings.theme if self._settings is not None else None
        download_factor, upload_factor = score_factors_for(theme_id)
        return snapshot(total_down, total_up, download_factor, upload_factor)

    def shutdown(self) -> None:
        self._flush_timer.stop()
        self.flush()
