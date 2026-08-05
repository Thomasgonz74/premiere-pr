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
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from PySide6.QtCore import QObject, Signal

from torrent2000.config.paths import get_share_limits_path
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord


@dataclass
class ShareLimit:
    time_limit_seconds: Optional[int]  # None = unlimited
    data_limit_bytes: Optional[int]  # None = unlimited
    # Wall-clock time.time(), not time.monotonic() -- this value is persisted
    # and reloaded in a later process, where monotonic()'s epoch is
    # unrelated to the one it was recorded under, making any elapsed-time
    # delta computed against it meaningless after a restart.
    started_at: float
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
        self._load()
        session_manager.torrent_status_updated.connect(self._on_status_updated)
        session_manager.torrent_removed.connect(self.untrack)

    def track(self, info_hash: str, time_limit_seconds: Optional[int], data_limit_bytes: Optional[int]) -> None:
        record = self._session_manager.get_record(info_hash)
        baseline = record.all_time_uploaded if record is not None else 0
        self._limits[info_hash] = ShareLimit(
            time_limit_seconds=time_limit_seconds,
            data_limit_bytes=data_limit_bytes,
            started_at=time.time(),
            uploaded_baseline=baseline,
        )
        self._save()

    def untrack(self, info_hash: str) -> None:
        if self._limits.pop(info_hash, None) is not None:
            self._save()

    def is_tracked(self, info_hash: str) -> bool:
        return info_hash in self._limits

    def limit_for(self, info_hash: str) -> Optional[ShareLimit]:
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
            self._save()

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        data = {info_hash: asdict(limit) for info_hash, limit in self._limits.items()}
        get_share_limits_path().write_text(json.dumps(data), encoding="utf-8")

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
