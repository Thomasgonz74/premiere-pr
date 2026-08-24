"""Automatic resume for torrents paused after a disk/file I/O error, once the
drive that dropped out (e.g. an external drive unplugged mid-write) reappears.

OFF BY DEFAULT (see Settings.auto_resume_on_disk_reconnect) -- the pause
itself (SessionManager._on_file_error, triggered by a file_error_alert)
always happens regardless of this setting; only the automatic *resume* here
is opt-in, same convention as BatteryPauseService's pause_on_battery_enabled.

The drive is matched by volume serial number rather than save-path/drive
letter, since a letter can be reassigned to a different disk entirely.
"""

import logging

from PySide6.QtCore import QObject

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.volume_serial import get_volume_serial
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 30_000


class DiskReconnectService(QObject):
    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        # save_path -> volume serial last seen while that path was reachable.
        # Refreshed every tick for every currently-known torrent's save_path
        # *before* it errors -- by the time a file_error_alert actually
        # fires, the drive may already be gone, so querying it only then
        # would just return None and defeat the whole point.
        self._last_known_serial: dict[str, int] = {}
        # info_hash -> (save_path, expected volume serial) for torrents
        # currently paused by a file error.
        self._pending: dict[str, tuple[str, int | None]] = {}

        session_manager.file_error.connect(self._on_file_error)
        session_manager.torrent_removed.connect(self._on_torrent_removed)
        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.check_now)

    def _on_file_error(self, info_hash: str, _message: str) -> None:
        record = self._session_manager.get_record(info_hash)
        if record is None or not record.save_path:
            return
        # ponytail: if this path was never seen healthy (no cached serial),
        # fall back to a live query -- usually None right after a disconnect,
        # so that torrent just won't be eligible for auto-resume. Upgrade:
        # snapshot serials at torrent-add time too, not just every tick.
        expected_serial = self._last_known_serial.get(record.save_path)
        if expected_serial is None:
            expected_serial = get_volume_serial(record.save_path)
        self._pending[info_hash] = (record.save_path, expected_serial)

    def _on_torrent_removed(self, info_hash: str) -> None:
        self._pending.pop(info_hash, None)

    def check_now(self) -> None:
        if not self._settings.auto_resume_on_disk_reconnect:
            return

        pending_paths = {path for path, _ in self._pending.values()}
        for record in self._session_manager.all_records():
            if record.save_path and record.save_path not in pending_paths:
                serial = get_volume_serial(record.save_path)
                if serial is not None:
                    self._last_known_serial[record.save_path] = serial

        for info_hash, (save_path, expected_serial) in list(self._pending.items()):
            if expected_serial is None:
                continue
            if get_volume_serial(save_path) != expected_serial:
                continue
            self._session_manager.resume_torrent(info_hash)
            self._pending.pop(info_hash, None)
