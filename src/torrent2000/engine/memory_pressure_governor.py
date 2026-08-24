"""Optional throttling under system memory pressure.

OFF BY DEFAULT (see Settings.memory_governor_enabled) -- this only ever does
anything once the user explicitly opts in from the Profile tab. Periodically
samples psutil.virtual_memory().percent; once it crosses
Settings.memory_governor_threshold_percent, it temporarily halves
max_active_downloads (via SessionManager.set_max_active_downloads -- a
live-session-only change, Settings.max_active_downloads itself is never
touched) and pauses RssFeedService's periodic feed checks and
HistoryService's disk writes (see their respective set_paused methods) until
memory usage drops back below the threshold, at which point everything is
restored exactly as it was.
"""

import logging

import psutil
from PySide6.QtCore import QObject

from torrent2000.config.settings import Settings
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.session_manager import SessionManager
from torrent2000.stats.history_service import HistoryService
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 30_000


class MemoryPressureGovernor(QObject):
    def __init__(
        self,
        session_manager: SessionManager,
        settings: Settings,
        rss_feed_service: RssFeedService,
        history_service: HistoryService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._rss_feed_service = rss_feed_service
        self._history_service = history_service
        self._throttling = False

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.check_now)

    def check_now(self) -> None:
        if not self._settings.memory_governor_enabled:
            if self._throttling:
                self._restore()  # user disabled it mid-throttle -- don't leave downloads/services stuck
            return

        if psutil.virtual_memory().percent >= self._settings.memory_governor_threshold_percent:
            if not self._throttling:
                self._apply_pressure()
        elif self._throttling:
            self._restore()

    def _apply_pressure(self) -> None:
        reduced = max(1, self._settings.max_active_downloads // 2)
        self._session_manager.set_max_active_downloads(reduced)
        self._rss_feed_service.set_paused(True)
        self._history_service.set_paused(True)
        self._throttling = True

    def _restore(self) -> None:
        self._session_manager.set_max_active_downloads(self._settings.max_active_downloads)
        self._rss_feed_service.set_paused(False)
        self._history_service.set_paused(False)
        self._throttling = False
