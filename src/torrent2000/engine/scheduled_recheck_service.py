"""Scheduled integrity recheck (catalogue idea "controle d'integrite
planifie") -- periodically force-rechecks finished torrents so silent
corruption (a bad sector, a partially-overwritten file) is caught before
it's discovered too late, e.g. right after the reconnection of a drive
already flagged by engine/disk_reconnect_service.py.

OFF BY DEFAULT (see Settings.scheduled_recheck_enabled), same convention as
every other opt-in automation in this project. Pure QTimer polling (like
bandwidth_scheduler.py), not event-driven -- there's no "a month has passed"
signal to react to.

Per-torrent last-checked timestamps are session-only (not persisted): a
restart simply resets the clock for every torrent rather than remembering
exactly when each was last verified. That's an acceptable simplification for
a background hygiene feature -- worst case a torrent gets rechecked a bit
sooner than the configured interval after a restart, never later than
CHECK_INTERVAL_MS off from what it would otherwise be.
"""

import time

from PySide6.QtCore import QObject

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentState
from torrent2000.utils.qt_timers import start_periodic_timer

CHECK_INTERVAL_MS = 60 * 60 * 1000  # hourly is plenty of granularity for a day-scale interval setting

_SECONDS_PER_DAY = 86400


class ScheduledRecheckService(QObject):
    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        # info_hash -> monotonic time this torrent was last force-rechecked
        # (or first noticed finished, for a torrent never rechecked yet).
        self._last_checked: dict[str, float] = {}

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.evaluate_now)

    def evaluate_now(self) -> None:
        if not self._settings.scheduled_recheck_enabled:
            return
        interval_seconds = max(1, self._settings.scheduled_recheck_interval_days) * _SECONDS_PER_DAY
        now = time.monotonic()
        finished_hashes = {
            record.info_hash for record in self._session_manager.all_records() if record.state == TorrentState.FINISHED
        }
        # Drop bookkeeping for torrents no longer finished/present (removed,
        # or resumed back to downloading after a manual recheck failure) so
        # this dict doesn't grow unbounded over a long-running session.
        for stale_hash in list(self._last_checked):
            if stale_hash not in finished_hashes:
                del self._last_checked[stale_hash]

        for info_hash in finished_hashes:
            last_checked = self._last_checked.get(info_hash)
            if last_checked is None:
                # First time seen finished -- starts the clock, does not
                # recheck immediately (avoids a burst of rechecks the moment
                # this feature is first enabled on an install with many
                # already-finished torrents).
                self._last_checked[info_hash] = now
                continue
            if now - last_checked >= interval_seconds:
                self._session_manager.recheck_torrent(info_hash)
                self._last_checked[info_hash] = now
