"""Watch-folder auto-import.

Periodically scans a user-configured folder for `*.torrent` files and adds
each one automatically (into the configured default download directory),
then moves the file into a `processed` subfolder of the watch folder so it
is never re-added on a later scan. A file that fails to add (duplicate
info-hash already in the session, corrupt/unparsable .torrent, ...) is
moved into a `failed` subfolder instead, so it is attempted at most once
rather than retried -- and logged -- forever on every scan. Purely
settings-driven: the service reads
`settings.watch_folder_enabled`/`watch_folder_path` fresh on every tick, so
toggling it from the Profile tab takes effect on the next scan without
needing a live-apply call.
"""

import logging
from pathlib import Path

import libtorrent as lt
from PySide6.QtCore import QObject

from torrent2000.config.settings import Settings
from torrent2000.engine.routing_rules import RoutingRuleStore, resolve_destination
from torrent2000.engine.session_manager import SessionManager
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 10_000
PROCESSED_SUBFOLDER = "processed"
FAILED_SUBFOLDER = "failed"


class WatchFolderService(QObject):
    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._routing_store = RoutingRuleStore()

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.scan_now)

    def scan_now(self) -> None:
        if not self._settings.watch_folder_enabled:
            return
        folder_str = self._settings.watch_folder_path
        if not folder_str:
            return
        folder = Path(folder_str)
        if not folder.is_dir():
            return

        processed_dir = folder / PROCESSED_SUBFOLDER
        failed_dir = folder / FAILED_SUBFOLDER
        # Non-recursive glob: files already moved into `processed`/`failed`
        # are never revisited, and neither pre-existing subfolder is
        # rescanned since it isn't itself named "*.torrent".
        for torrent_path in sorted(folder.glob("*.torrent")):
            if not torrent_path.is_file():
                continue
            destination = resolve_destination(
                self._routing_store.list_rules(),
                self._settings.default_download_dir,
                name=torrent_path.stem,
                trackers=self._read_trackers(torrent_path),
            )
            try:
                self._session_manager.add_torrent_from_file(str(torrent_path), destination)
            except Exception:
                # A permanently-failing file (already in the session, corrupt,
                # etc.) would otherwise be retried -- and log an identical
                # traceback -- every CHECK_INTERVAL_MS forever. Quarantine it
                # like a processed file so it's attempted at most once.
                logger.exception("Watch folder: failed to add %s -- moving to '%s'", torrent_path.name, FAILED_SUBFOLDER)
                self._move_to(torrent_path, failed_dir)
                continue
            self._move_to(torrent_path, processed_dir)

    @staticmethod
    def _move_to(torrent_path: Path, target_dir: Path) -> None:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            torrent_path.replace(target_dir / torrent_path.name)
        except OSError:
            logger.exception("Watch folder: failed to move %s into '%s'", torrent_path.name, target_dir.name)

    @staticmethod
    def _read_trackers(torrent_path: Path) -> list[str] | None:
        """Unlike the RSS/add-tab-magnet routing paths, the .torrent file is
        already fully on disk here, so its tracker list CAN be read up
        front -- tracker-matching routing rules are fully usable for a watch
        folder. Returns None (not []) on a still-being-written or corrupt
        file, so resolve_destination correctly treats "couldn't read
        trackers" as missing information rather than "genuinely zero
        trackers"."""
        try:
            return [entry.url for entry in lt.torrent_info(str(torrent_path)).trackers()]
        except Exception:
            return None
