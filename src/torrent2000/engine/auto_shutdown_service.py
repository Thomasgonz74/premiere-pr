"""Optional auto-shutdown once every currently-tracked torrent has stopped
actively downloading.

OFF BY DEFAULT (see Settings.auto_shutdown_enabled) -- this only ever does
anything once the user explicitly opts in from the Profile tab. Each time a
torrent finishes, if the feature is enabled and no torrent is left actively
downloading, a cancellable countdown starts (see `shutdown_countdown_started`
/ `cancel_shutdown`); if it elapses without being cancelled (and the setting
wasn't disabled in the meantime), the OS shutdown/hibernate command actually
runs.
"""

import logging
import os

from PySide6.QtCore import QObject, QTimer, Signal

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import ACTIVE_DOWNLOAD_STATES, TorrentRecord

logger = logging.getLogger(__name__)


def all_torrents_idle(records: list[TorrentRecord]) -> bool:
    """True when none of the given records are still actively downloading
    (i.e. every torrent has finished, is seeding, paused, awaiting analysis,
    or errored)."""
    return not any(record.state in ACTIVE_DOWNLOAD_STATES for record in records)


class AutoShutdownService(QObject):
    shutdown_countdown_started = Signal(int)  # delay in seconds

    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._countdown_timer: QTimer | None = None
        self._pending_action: str | None = None

        session_manager.torrent_finished.connect(self._on_torrent_finished)

    def _on_torrent_finished(self, info_hash: str) -> None:
        if not self._settings.auto_shutdown_enabled:
            return
        if self._pending_action is not None:
            return  # a countdown is already running
        if not all_torrents_idle(self._session_manager.all_records()):
            return

        self._pending_action = self._settings.auto_shutdown_action
        delay = self._settings.auto_shutdown_delay_seconds
        self.shutdown_countdown_started.emit(delay)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setSingleShot(True)
        self._countdown_timer.timeout.connect(self._on_countdown_elapsed)
        self._countdown_timer.start(max(0, delay) * 1000)

    def cancel_shutdown(self) -> None:
        """Called by whoever shows the countdown dialog when the user clicks
        "Annuler". Safe to call even if no countdown is currently pending."""
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer.deleteLater()
            self._countdown_timer = None
        self._pending_action = None

    def _on_countdown_elapsed(self) -> None:
        action = self._pending_action
        self._countdown_timer = None
        self._pending_action = None
        if action is None:
            return  # cancelled just as the timer fired
        if not self._settings.auto_shutdown_enabled:
            return  # disabled in the meantime -- never actually shut down
        self._execute(action)

    def _execute(self, action: str) -> None:
        """The single line that actually talks to the OS -- kept as its own
        method so tests can monkeypatch/mock it out and never trigger a real
        shutdown/hibernate."""
        logger.warning("Auto-shutdown: executing %s now", action)
        # os.system is safe here: both commands are fixed string literals with
        # no interpolated/user-controlled input (action is constrained to the
        # "shutdown"/"hibernate" branch above, never passed into the string),
        # so there is no command-injection surface. subprocess.run isn't
        # needed for a static, argument-free system command like this.
        if action == "hibernate":
            os.system("shutdown /h")
        else:
            os.system("shutdown /s /t 0")
