"""Warns when free disk space at an actively-downloading torrent's save path
drops below a configured threshold.

Only emits once per save path per "low" episode: once a path has warned, it
stays quiet on subsequent ticks until free space recovers above the
threshold (or the torrent stops being active), so the user isn't spammed
every 30 seconds while a disk stays full.
"""

import logging
import shutil

from PySide6.QtCore import QObject, QTimer, Signal

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentState
from torrent2000.i18n.translator import tr

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 30_000

# "Actively downloading" here mirrors the definition used by
# engine/auto_shutdown_service.py's idle check: still consuming disk space,
# as opposed to paused/seeding/finished/errored torrents that no longer are.
_ACTIVE_DOWNLOAD_STATES = {
    TorrentState.DOWNLOADING,
    TorrentState.QUEUED,
    TorrentState.CHECKING_METADATA,
}


def free_space_mb(path: str) -> float | None:
    """Returns free space at `path` in megabytes, or None if it can't be
    determined (e.g. the path doesn't exist yet, or is on an unreachable
    network/removable drive)."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.free / (1024 * 1024)


class DiskSpaceMonitor(QObject):
    low_space_warning = Signal(str, str)  # save_path, human-readable message

    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._warned_paths: set[str] = set()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_now)
        self._timer.start(CHECK_INTERVAL_MS)

    def check_now(self) -> None:
        if not self._settings.disk_space_warning_enabled:
            self._warned_paths.clear()
            return

        threshold = self._settings.disk_space_warning_threshold_mb
        active_paths = {
            record.save_path
            for record in self._session_manager.all_records()
            if record.state in _ACTIVE_DOWNLOAD_STATES and record.save_path
        }

        for path in active_paths:
            free_mb = free_space_mb(path)
            if free_mb is None:
                continue
            if free_mb < threshold:
                if path not in self._warned_paths:
                    self._warned_paths.add(path)
                    message = tr("disk_space.low_space_warning", path=path, free_mb=f"{free_mb:.0f}", threshold=threshold)
                    self.low_space_warning.emit(path, message)
            else:
                self._warned_paths.discard(path)

        # Drop bookkeeping for paths that are no longer actively downloading
        # to, so a later download to the same path starts with a clean slate.
        self._warned_paths &= active_paths
