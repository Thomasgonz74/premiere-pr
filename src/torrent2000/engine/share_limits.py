"""Optional time/data caps for torrents seeded via the "Partage" tab.

This only ever pauses a torrent once a limit is reached -- it never touches
what gets reported to a tracker, and never fabricates upload activity. See
ui/tabs/share_tab.py for the UI this backs.

Which torrents are tracked here (and their limits/progress) is persisted to
disk so ShareTab can restore its table on the next launch -- SessionManager's
own resume-data persistence only knows about torrents at the libtorrent
level, it has no notion of "this one was added via the Partage tab".
"""

import json
import os
import time
from dataclasses import asdict, dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal

from torrent2000.config.paths import get_share_limits_path
from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState


@dataclass
class ShareLimit:
    time_limit_seconds: int | None  # None = unlimited
    data_limit_bytes: int | None  # None = unlimited
    # Ratio is naturally an all-time concept (a private tracker's ratio
    # requirement applies against the torrent's whole lifetime), unlike the
    # time/data caps above which are measured since tracking started -- see
    # ShareLimitService._on_status_updated for how it's computed accordingly.
    ratio_limit: float | None  # None = unlimited
    # Wall-clock time.time(), not time.monotonic() -- this value is persisted
    # and reloaded in a later process, where monotonic()'s epoch is
    # unrelated to the one it was recorded under, making any elapsed-time
    # delta computed against it meaningless after a restart.
    started_at: float
    uploaded_baseline: int  # all_time_uploaded at tracking start, to isolate this session's upload
    reached: bool = field(default=False)
    reached_reason: str | None = field(default=None)  # "time" | "data" | "ratio"


class ShareLimitService(QObject):
    """Tracks elapsed seeding time and bytes uploaded *since being added to
    the Partage tab* for each torrent it's asked to track, and pauses that
    torrent once either configured limit is hit."""

    limit_reached = Signal(str, str)  # info_hash, reason ("time" | "data")

    # Coalesces bursts of near-simultaneous save requests (e.g. tracking
    # several torrents from the Partage tab in a row, or several limits
    # being reached within the same status-update tick) into one disk
    # write. 500ms is short enough that a single user-driven action (e.g.
    # clicking "track") is still persisted well before anyone could
    # plausibly force-quit, but long enough to absorb a rapid-fire burst
    # into a single write.
    _SAVE_DEBOUNCE_MS = 500

    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._limits: dict[str, ShareLimit] = {}
        self._load()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self._SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save)
        session_manager.torrent_status_updated.connect(self._on_status_updated)
        session_manager.torrent_removed.connect(self.untrack)

    def track(
        self,
        info_hash: str,
        time_limit_seconds: int | None,
        data_limit_bytes: int | None,
        ratio_limit: float | None = None,
    ) -> None:
        record = self._session_manager.get_record(info_hash)
        baseline = record.all_time_uploaded if record is not None else 0
        self._limits[info_hash] = ShareLimit(
            time_limit_seconds=time_limit_seconds,
            data_limit_bytes=data_limit_bytes,
            ratio_limit=ratio_limit,
            started_at=time.time(),
            uploaded_baseline=baseline,
        )
        self._schedule_save()

    def apply_default_policy_if_enabled(self, info_hash: str) -> None:
        """Auto-track a torrent under the user's configured default share
        policy the first time it's seen seeding, if the policy is enabled and
        the torrent isn't already tracked (e.g. added manually via the
        Partage tab with its own explicit limits) -- see _on_status_updated,
        which calls this on every SEEDING transition."""
        if not self._settings.default_share_policy_enabled or self.is_tracked(info_hash):
            return
        time_limit = self._settings.default_share_time_limit_hours * 3600 or None
        data_limit = self._settings.default_share_data_limit_mb * 1024 * 1024 or None
        ratio_limit = self._settings.default_share_ratio_limit or None
        self.track(info_hash, time_limit_seconds=time_limit, data_limit_bytes=data_limit, ratio_limit=ratio_limit)

    def untrack(self, info_hash: str) -> None:
        if self._limits.pop(info_hash, None) is not None:
            self._schedule_save()

    def is_tracked(self, info_hash: str) -> bool:
        return info_hash in self._limits

    def limit_for(self, info_hash: str) -> ShareLimit | None:
        return self._limits.get(info_hash)

    def tracked_info_hashes(self) -> list[str]:
        return list(self._limits.keys())

    def progress(self, info_hash: str, record: TorrentRecord) -> tuple[float, int]:
        """Return (elapsed_seconds, uploaded_bytes_since_tracking_started)."""
        limit = self._limits.get(info_hash)
        if limit is None:
            return 0.0, 0
        elapsed = time.time() - limit.started_at
        uploaded = max(0, record.all_time_uploaded - limit.uploaded_baseline)
        return elapsed, uploaded

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        if record.state == TorrentState.SEEDING:
            self.apply_default_policy_if_enabled(info_hash)

        limit = self._limits.get(info_hash)
        if limit is None or limit.reached:
            return
        elapsed, uploaded = self.progress(info_hash, record)

        reason = None
        if limit.time_limit_seconds is not None and elapsed >= limit.time_limit_seconds:
            reason = "time"
        elif limit.data_limit_bytes is not None and uploaded >= limit.data_limit_bytes:
            reason = "data"
        elif limit.ratio_limit is not None and limit.ratio_limit > 0:
            downloaded = record.all_time_downloaded
            if downloaded <= 0 and record.progress >= 1.0 and record.total_size > 0:
                # Torrent added via the Partage tab's "Dossier contenant deja
                # les fichiers" (data already on disk): libtorrent only
                # hash-checks local files in that case, it never reports that
                # as "downloaded", so all_time_downloaded stays 0 forever
                # even though a full copy is being seeded. Fall back to the
                # verified local size so the ratio cap still has a usable
                # denominator instead of never being able to fire.
                downloaded = record.total_size
            if downloaded > 0 and (record.all_time_uploaded / downloaded) >= limit.ratio_limit:
                reason = "ratio"

        if reason is not None:
            limit.reached = True
            limit.reached_reason = reason
            self._session_manager.pause_torrent(info_hash)
            self.limit_reached.emit(info_hash, reason)
            self._schedule_save()

    # ------------------------------------------------------------- persistence

    def _schedule_save(self) -> None:
        """Request a debounced save -- (re)starts the single-shot timer, so a
        burst of calls within the debounce window collapses into one write."""
        self._save_timer.start()

    def flush_pending_save(self) -> None:
        """Force an immediate write if a debounced save is currently
        pending. Meant to be called on app shutdown so the last change in a
        rapid burst isn't lost if the process exits before the debounce
        timer would otherwise have fired."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save()

    def _save(self) -> None:
        data = {info_hash: asdict(limit) for info_hash, limit in self._limits.items()}
        path = get_share_limits_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_share_limits_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for info_hash, fields in data.items():
            try:
                self._limits[info_hash] = ShareLimit(**fields)
            except TypeError:
                continue  # malformed/outdated entry -- skip rather than crash on startup
