"""Watch-folder auto-import.

Periodically scans a user-configured folder for `*.torrent` files and adds
each one automatically (into the configured default download directory),
then moves the processed file into a `processed` subfolder of the watch
folder so it is never re-added on a later scan. Purely settings-driven: the
service reads `settings.watch_folder_enabled`/`watch_folder_path` fresh on
every tick, so toggling it from the Profile tab takes effect on the next
scan without needing a live-apply call.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 10_000
PROCESSED_SUBFOLDER = "processed"


class WatchFolderService(QObject):
    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.scan_now)
        self._timer.start(CHECK_INTERVAL_MS)

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
        # Non-recursive glob: files already moved into `processed` are never
        # revisited, and any pre-existing "processed" subfolder is skipped
        # since it isn't itself named "*.torrent".
        for torrent_path in sorted(folder.glob("*.torrent")):
            if not torrent_path.is_file():
                continue
            try:
                self._session_manager.add_torrent_from_file(str(torrent_path), self._settings.default_download_dir)
            except Exception:
                logger.exception("Watch folder: failed to add %s", torrent_path)
                continue
            try:
                processed_dir.mkdir(parents=True, exist_ok=True)
                torrent_path.replace(processed_dir / torrent_path.name)
            except OSError:
                logger.exception("Watch folder: failed to move processed file %s", torrent_path)
