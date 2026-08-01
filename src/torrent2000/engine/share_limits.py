"""Optional time/data caps for torrents seeded via the "Partage" tab.

This only ever pauses a torrent once a limit is reached -- it never touches
what gets reported to a tracker, and never fabricates upload activity. See
ui/tabs/share_tab.py for the UI this backs.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QObject, Signal

from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord


@dataclass
class ShareLimit:
    time_limit_seconds: Optional[int]  # None = unlimited
    data_limit_bytes: Optional[int]  # None = unlimited
    started_at: float  # time.monotonic() when tracking began
    uploaded_baseline: int  # all_time_uploaded at tracking start, to isolate this session's upload
    reached: bool = field(default=False)
    reached_reason: Optional[str] = field(default=None)  # "time" | "data"


class ShareLimitService(QObject):
    """Tracks elapsed seeding time and bytes uploaded *since being added to
    the Partage tab* for each torrent it's asked to track, and pauses that
    torrent once either configured limit is hit."""

    limit_reached = Signal(str, str)  # info_hash, reason ("time" | "data")

    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._limits: dict[str, ShareLimit] = {}
        session_manager.torrent_status_updated.connect(self._on_status_updated)

    def track(self, info_hash: str, time_limit_seconds: Optional[int], data_limit_bytes: Optional[int]) -> None:
        record = self._session_manager.get_record(info_hash)
        baseline = record.all_time_uploaded if record is not None else 0
        self._limits[info_hash] = ShareLimit(
            time_limit_seconds=time_limit_seconds,
            data_limit_bytes=data_limit_bytes,
            started_at=time.monotonic(),
            uploaded_baseline=baseline,
        )

    def untrack(self, info_hash: str) -> None:
        self._limits.pop(info_hash, None)

    def is_tracked(self, info_hash: str) -> bool:
        return info_hash in self._limits

    def limit_for(self, info_hash: str) -> Optional[ShareLimit]:
        return self._limits.get(info_hash)

    def progress(self, info_hash: str, record: TorrentRecord) -> tuple[float, int]:
        """Return (elapsed_seconds, uploaded_bytes_since_tracking_started)."""
        limit = self._limits.get(info_hash)
        if limit is None:
            return 0.0, 0
        elapsed = time.monotonic() - limit.started_at
        uploaded = max(0, record.all_time_uploaded - limit.uploaded_baseline)
        return elapsed, uploaded

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        limit = self._limits.get(info_hash)
        if limit is None or limit.reached:
            return
        elapsed, uploaded = self.progress(info_hash, record)

        reason = None
        if limit.time_limit_seconds is not None and elapsed >= limit.time_limit_seconds:
            reason = "time"
        elif limit.data_limit_bytes is not None and uploaded >= limit.data_limit_bytes:
            reason = "data"

        if reason is not None:
            limit.reached = True
            limit.reached_reason = reason
            self._session_manager.pause_torrent(info_hash)
            self.limit_reached.emit(info_hash, reason)
