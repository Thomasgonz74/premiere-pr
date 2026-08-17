"""Optional pause/resume of active downloads based on AC power state.

OFF BY DEFAULT (see Settings.pause_on_battery_enabled) -- this only ever does
anything once the user explicitly opts in from the Profile tab. On battery
power it pauses every torrent that's actively downloading and remembers
which ones it paused; once external power returns, it resumes exactly those
torrents -- never one the user had already paused manually before the
machine was even unplugged.
"""

import logging

import psutil
from PySide6.QtCore import QObject

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import ACTIVE_DOWNLOAD_STATES
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 30_000


class BatteryPauseService(QObject):
    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._paused_by_us: set[str] = set()

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.check_now)

    def check_now(self) -> None:
        if not self._settings.pause_on_battery_enabled:
            return

        battery = psutil.sensors_battery()
        if battery is None:
            return  # desktop with no battery -- nothing to do

        if battery.power_plugged:
            self._resume_previously_paused()
        else:
            self._pause_active_downloads()

    def _pause_active_downloads(self) -> None:
        for record in self._session_manager.all_records():
            if record.state in ACTIVE_DOWNLOAD_STATES:
                self._session_manager.pause_torrent(record.info_hash)
                self._paused_by_us.add(record.info_hash)

    def _resume_previously_paused(self) -> None:
        for info_hash in self._paused_by_us:
            self._session_manager.resume_torrent(info_hash)
        self._paused_by_us.clear()
