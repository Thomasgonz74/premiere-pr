"""Optional turtle-mode toggle triggered by real system-wide input idle time.

OFF BY DEFAULT (see Settings.idle_bandwidth_reduction_enabled) -- this only
ever does anything once the user explicitly opts in from the Profile tab.
Measures idle time via the Windows GetLastInputInfo API (system-wide mouse/
keyboard input, not just activity inside this app's own window -- the goal is
"user stepped away from the whole machine", not "user stopped clicking in
torrent2000"). Once idle for at least idle_bandwidth_reduction_minutes,
engages BandwidthScheduler.set_turtle_mode(True) -- an existing, restorable
rate-limit override (see bandwidth_scheduler.py) -- and disables it again the
moment activity resumes, which restores whatever rate the schedule/base
settings say should be active right then. Windows-only (GetLastInputInfo),
matching this project's Windows-only scope (see engine/disk_allocation.py).
"""

import ctypes
import logging

from PySide6.QtCore import QObject

from torrent2000.config.settings import Settings
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 30_000
_MS_PER_MINUTE = 60_000
_TICK_WRAP = 1 << 32  # GetTickCount() and LASTINPUTINFO.dwTime are both 32-bit, wrap at the same point


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("dwTime", ctypes.c_uint32)]


def idle_ms() -> int | None:
    """Milliseconds since the last system-wide keyboard/mouse input, or None
    if the query fails -- non-Windows (ctypes.windll doesn't exist there) or
    the call itself errors. Mirrors disk_allocation.compressed_file_size's
    ctypes error handling."""
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick_count = ctypes.windll.kernel32.GetTickCount()
    except (AttributeError, OSError):
        return None
    return (tick_count - info.dwTime) % _TICK_WRAP


class IdleActivityService(QObject):
    def __init__(self, bandwidth_scheduler: BandwidthScheduler, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._bandwidth_scheduler = bandwidth_scheduler
        self._settings = settings
        self._turtle_active = False

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.check_now)

    def check_now(self) -> None:
        if not self._settings.idle_bandwidth_reduction_enabled:
            if self._turtle_active:
                self._deactivate()  # user disabled it mid-idle -- don't leave turtle mode stuck on
            return

        ms = idle_ms()
        if ms is None:
            return  # can't measure idle time right now -- leave current state alone

        threshold_ms = self._settings.idle_bandwidth_reduction_minutes * _MS_PER_MINUTE
        is_idle = ms >= threshold_ms
        if is_idle and not self._turtle_active:
            self._activate()
        elif not is_idle and self._turtle_active:
            self._deactivate()

    def _activate(self) -> None:
        self._bandwidth_scheduler.set_turtle_mode(True)
        self._turtle_active = True

    def _deactivate(self) -> None:
        self._bandwidth_scheduler.set_turtle_mode(False)
        self._turtle_active = False
