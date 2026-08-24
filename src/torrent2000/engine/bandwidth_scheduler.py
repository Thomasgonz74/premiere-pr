"""Time-of-day bandwidth scheduling: apply a reduced rate limit during a
configured daily window (e.g. throttled during the day), and Settings'
normal limits the rest of the time.
"""

from datetime import datetime

from PySide6.QtCore import QObject

from torrent2000.config.settings import BandwidthSchedule, Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.utils.qt_timers import start_periodic_timer

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
        # Session-only, deliberately not part of Settings -- see
        # set_turtle_mode.
        self._turtle_mode_enabled = False

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.evaluate_now)
        self.evaluate_now()

    def evaluate_now(self) -> None:
        schedule = self._settings.bandwidth_schedule
        should_throttle = schedule.enabled and is_within_window(
            datetime.now().hour, schedule.start_hour, schedule.end_hour
        )
        if should_throttle == self._currently_throttled:
            return  # no state change, avoid redundant apply_settings calls every tick
        self._currently_throttled = should_throttle
        if self._turtle_mode_enabled:
            # Turtle mode overrides whatever the schedule would otherwise
            # apply -- _currently_throttled above still gets tracked so
            # set_turtle_mode(enabled=False) later restores the right value.
            return
        self._apply_current_limits()

    def _apply_current_limits(self) -> None:
        download_kbps, upload_kbps = self._current_limits()
        self._session_manager.set_rate_limits(download_kbps, upload_kbps)

    def _current_limits(self) -> tuple[int, int]:
        """What the schedule/base settings say the rate limit should be
        right now, ignoring turtle mode -- the single "what should the rate
        be" decision shared by evaluate_now's periodic re-checks and by
        set_turtle_mode(enabled=False), which restores exactly this instead
        of duplicating the schedule-vs-base logic."""
        if self._currently_throttled:
            schedule = self._settings.bandwidth_schedule
            return schedule.limited_download_kbps, schedule.limited_upload_kbps
        return self._settings.download_rate_limit_kbps, self._settings.upload_rate_limit_kbps

    def current_download_limit_kbps(self) -> int:
        """The download limit (KB/s, 0 = unlimited) from the base setting or
        the active schedule window, whichever applies right now. Public
        wrapper around _current_limits() so callers outside this module
        (e.g. the "why is this slow" explainer) don't need to reach into a
        private method. Note: doesn't reflect turtle mode -- set_turtle_mode
        applies its rate directly without recording it here, and nothing in
        this codebase currently calls set_turtle_mode."""
        return self._current_limits()[0]

    def settings_changed(self) -> None:
        """Call after the user edits schedule/rate-limit settings so a
        currently-active window re-evaluates against the new values
        immediately instead of waiting for the next timer tick."""
        self._currently_throttled = None
        self.evaluate_now()

    def set_turtle_mode(self, enabled: bool, turtle_download_kbps: int = 50, turtle_upload_kbps: int = 20) -> None:
        """Quick, transient rate-limit override for a "slow down right now"
        toggle -- while enabled, forces the turtle values regardless of the
        schedule; disabling restores whatever _current_limits() says should
        be active at that moment. Kept as a plain instance attribute rather
        than a Settings field: this is a session toggle, not a saved
        preference."""
        self._turtle_mode_enabled = enabled
        if enabled:
            self._session_manager.set_rate_limits(turtle_download_kbps, turtle_upload_kbps)
        else:
            self._apply_current_limits()
