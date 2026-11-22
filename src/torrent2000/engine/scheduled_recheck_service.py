"""Scheduled integrity recheck (catalogue idea "controle d'integrite
planifie") -- periodically force-rechecks complete torrents so silent
corruption (a bad sector, a partially-overwritten file) is caught before
it's discovered too late, e.g. right after the reconnection of a drive
already flagged by engine/disk_reconnect_service.py.

OFF BY DEFAULT (see Settings.scheduled_recheck_enabled), same convention as
every other opt-in automation in this project. Pure QTimer polling (like
bandwidth_scheduler.py), not event-driven -- there's no "a month has passed"
signal to react to.

Per-torrent last-checked wall-clock timestamps are persisted (see
get_scheduled_recheck_path): session-only clocks restarted on every launch,
so anyone who rebooted within the interval never got a recheck at all.
"""

import json
import logging
import os
import time

from PySide6.QtCore import QObject, QTimer

from torrent2000.config.paths import get_scheduled_recheck_path
from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 60 * 60 * 1000  # hourly is plenty of granularity for a day-scale interval setting
# The first evaluation, so a session shorter than an hour still gets its
# overdue rechecks: not at startup, where the async restore has left the
# records missing or at progress 0 -- an evaluation then would drop their
# saved clocks (see evaluate_now).
FIRST_CHECK_DELAY_MS = 5 * 60 * 1000

_SECONDS_PER_DAY = 86400


class ScheduledRecheckService(QObject):
    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        # info_hash -> time.time() this torrent was last force-rechecked
        # (or first noticed complete, for a torrent never rechecked yet).
        self._last_checked: dict[str, float] = self._load()

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.evaluate_now)
        QTimer.singleShot(FIRST_CHECK_DELAY_MS, self, self.evaluate_now)

    def evaluate_now(self) -> None:
        if not self._settings.scheduled_recheck_enabled:
            return
        interval_seconds = max(1, self._settings.scheduled_recheck_interval_days) * _SECONDS_PER_DAY
        now = time.time()
        before = dict(self._last_checked)
        # progress, not state: a fully downloaded torrent is SEEDING (or
        # PAUSED); FINISHED only means the wanted part of a partial
        # selection is done.
        finished_hashes = {r.info_hash for r in self._session_manager.all_records() if r.progress >= 1.0}
        # Drop bookkeeping for torrents no longer complete/present (removed,
        # or resumed back to downloading after a manual recheck failure) so
        # this dict doesn't grow unbounded.
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
            # Paused ones included: recheck_torrent checks a paused torrent
            # and leaves it paused.
            if now - last_checked >= interval_seconds:
                self._session_manager.recheck_torrent(info_hash)
                self._last_checked[info_hash] = now

        if self._last_checked != before:
            self._save()

    def _save(self) -> None:
        path = get_scheduled_recheck_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp_path.write_text(json.dumps(self._last_checked), encoding="utf-8")
            os.replace(tmp_path, path)
        except OSError:
            logger.exception("Failed to save scheduled recheck timestamps")

    @staticmethod
    def _load() -> dict[str, float]:
        try:
            data = json.loads(get_scheduled_recheck_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: float(v) for k, v in data.items() if isinstance(k, str) and isinstance(v, (int, float))}
