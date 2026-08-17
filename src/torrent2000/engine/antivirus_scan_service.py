"""Optional Windows Defender scan of a torrent's files once it finishes
downloading.

OFF BY DEFAULT (see Settings.scan_completed_files_with_defender) -- this only
ever does anything once the user explicitly opts in from the Profile tab's
Security section. This is entirely local and silent by design, matching the
project's no-telemetry philosophy: it only ever invokes the OS's own
already-installed Defender binary (MpCmdRun.exe) against the torrent's own
save path, nothing is sent anywhere, and nothing is surfaced to the user UI.
It never creates a Defender exclusion -- only ever scans.

The scan itself runs in a QRunnable submitted to QThreadPool.globalInstance()
(matching the pattern in engine/rss_feed_service.py's _FetchFeedRunnable),
since MpCmdRun.exe can take a while on large data and must never block the
GUI thread.
"""

import logging
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager

logger = logging.getLogger(__name__)

SCAN_TIMEOUT_SECONDS = 300

_CLASSIC_MPCMDRUN_PATH = Path(r"C:\Program Files\Windows Defender\MpCmdRun.exe")
_PLATFORM_DIR = Path(r"C:\ProgramData\Microsoft\Windows Defender\platform")


def find_mpcmdrun() -> str | None:
    """Locates MpCmdRun.exe, which is not reliably on PATH. Tries, in order:
    PATH, the classic install path, then the newest versioned platform
    directory Defender updates itself into. Returns None if none exist."""
    on_path = shutil.which("MpCmdRun.exe")
    if on_path:
        return on_path

    if _CLASSIC_MPCMDRUN_PATH.exists():
        return str(_CLASSIC_MPCMDRUN_PATH)

    candidates = list(_PLATFORM_DIR.glob("*/MpCmdRun.exe"))
    if not candidates:
        return None
    newest = max(candidates, key=lambda p: p.parent.name)
    return str(newest)


class _ScanRunnable(QRunnable):
    def __init__(self, save_path: str) -> None:
        super().__init__()
        self._save_path = save_path

    def run(self) -> None:
        mpcmdrun_path = find_mpcmdrun()
        if mpcmdrun_path is None:
            logger.warning("Defender scan skipped: MpCmdRun.exe not found")
            return

        try:
            result = subprocess.run(
                [mpcmdrun_path, "-Scan", "-ScanType", "3", "-File", self._save_path],
                capture_output=True,
                timeout=SCAN_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.exception("Defender scan of %s failed to run", self._save_path)
            return

        logger.info("Defender scan of %s finished with return code %s", self._save_path, result.returncode)


class AntivirusScanService(QObject):
    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings

        session_manager.torrent_finished.connect(self._on_torrent_finished)

    def _on_torrent_finished(self, info_hash: str) -> None:
        if not self._settings.scan_completed_files_with_defender:
            return
        record = self._session_manager.get_record(info_hash)
        if record is None or not record.save_path:
            return
        runnable = _ScanRunnable(record.save_path)
        QThreadPool.globalInstance().start(runnable)
