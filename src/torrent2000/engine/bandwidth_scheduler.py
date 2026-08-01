"""Time-of-day bandwidth scheduling: apply a reduced rate limit during a
configured daily window (e.g. throttled during the day), and Settings'
normal limits the rest of the time.
"""

from datetime import datetime

from PySide6.QtCore import QObject, QTimer

from torrent2000.config.settings import BandwidthSchedule, Settings
from torrent2000.engine.session_manager import SessionManager

CHECK_INTERVAL_MS = 30_000  # checking every 30s is plenty for hour-granularity windows


def is_within_window(hour: int, start_hour: int, end_hour: int) -> bool:
    """Pure hour-of-day window check. Handles windows that wrap past
    midnight (e.g. start=22, end=6 means 22:00-06:00)."""
    if start_hour == end_hour:
        return False  # a zero-width window never applies
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


class BandwidthScheduler(QObject):
    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._currently_throttled: bool | None = None  # None = not yet evaluated

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.evaluate_now)
        self._timer.start(CHECK_INTERVAL_MS)
        self.evaluate_now()

    def evaluate_now(self) -> None:
        schedule = self._settings.bandwidth_schedule
        if not schedule.enabled:
            if self._currently_throttled:
                self._apply_normal_limits()
            self._currently_throttled = False
            return

        should_throttle = is_within_window(datetime.now().hour, schedule.start_hour, schedule.end_hour)
        if should_throttle == self._currently_throttled:
            return  # no state change, avoid redundant apply_settings calls every tick

        if should_throttle:
            self._session_manager.set_rate_limits(schedule.limited_download_kbps, schedule.limited_upload_kbps)
        else:
            self._apply_normal_limits()
        self._currently_throttled = should_throttle

    def _apply_normal_limits(self) -> None:
        self._session_manager.set_rate_limits(
            self._settings.download_rate_limit_kbps, self._settings.upload_rate_limit_kbps
        )

    def settings_changed(self) -> None:
        """Call after the user edits schedule/rate-limit settings so a
        currently-active window re-evaluates against the new values
        immediately instead of waiting for the next timer tick."""
        self._currently_throttled = None
        self.evaluate_now()
