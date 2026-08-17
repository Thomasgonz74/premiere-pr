from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


def start_periodic_timer(parent: QObject, interval_ms: int, callback: Callable[[], None]) -> QTimer:
    """Creates, wires, and starts a repeating QTimer parented to `parent` --
    the QTimer(self); timer.timeout.connect(callback); timer.start(ms)
    sequence every polling background service (bandwidth scheduler, watch
    folder, disk space monitor, RSS feed checks, session status/resume-data
    ticks) needs. Returns the QTimer so the caller can keep a reference
    (stop it, read isActive(), etc.) exactly as if it had built it inline."""
    timer = QTimer(parent)
    timer.timeout.connect(callback)
    timer.start(interval_ms)
    return timer
