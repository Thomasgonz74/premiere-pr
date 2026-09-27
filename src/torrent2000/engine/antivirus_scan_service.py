"""Optional Windows Defender scan of a torrent's files once it finishes
downloading.

OFF BY DEFAULT (see Settings.scan_completed_files_with_defender) -- this only
ever does anything once the user explicitly opts in from the Profile tab's
Security section. This is entirely local and silent by design, matching the
project's no-telemetry philosophy: it only ever invokes the OS's own
already-installed Defender binary (MpCmdRun.exe) against the torrent's own
files, nothing is sent anywhere, and nothing is surfaced to the user UI.
It never creates a Defender exclusion -- only ever scans.

The scan itself runs in a QRunnable submitted to QThreadPool.globalInstance()
(matching the pattern in engine/rss_feed_service.py's _FetchFeedRunnable),
since MpCmdRun.exe can take a while on large data and must never block the
GUI thread.
"""

import logging
import shutil
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager, _is_confined

logger = logging.getLogger(__name__)

SCAN_TIMEOUT_SECONDS = 300

_CLASSIC_MPCMDRUN_PATH = Path(r"C:\Program Files\Windows Defender\MpCmdRun.exe")
_PLATFORM_DIR = Path(r"C:\ProgramData\Microsoft\Windows Defender\platform")

# Set once at quit (cancel_running_scans): Qt waits for every running
# QThreadPool task before the process can exit, so a scan in progress must
# not be allowed to hold it open for up to SCAN_TIMEOUT_SECONDS.
_cancel_event = threading.Event()


def cancel_running_scans() -> None:
    """Called once at quit: a running scan is killed within about a second."""
    _cancel_event.set()


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


def _scan_target(save_path: str, name: str) -> str:
    """The torrent's own file/folder -- save_path alone is the download
    folder every torrent shares (Downloads/Torrent2000 by default), so
    scanning it re-reads the whole library on each finished torrent. Falls
    back to save_path when the name is empty, doesn't exist on disk (e.g.
    renamed), or escapes save_path: the name comes from the torrent's own
    metadata, so a crafted ".." or absolute name must not widen the scan."""
    if name:
        # _is_confined expects an already-resolved root: an unresolved one
        # (junction, subst or mapped drive, 8.3 name) never contains the
        # resolved target, which would silently fall back to the whole library.
        try:
            root = Path(save_path).resolve()
        except (OSError, ValueError):
            return save_path
        target = Path(save_path) / name
        if _is_confined(target, root) and target.exists():
            return str(target)
    return save_path


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
            process = subprocess.Popen(
                [mpcmdrun_path, "-Scan", "-ScanType", "3", "-File", self._save_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            logger.exception("Defender scan of %s failed to run", self._save_path)
            return

        # Polled in 1 s waits (one per loop turn, so the turn count is the
        # elapsed time) rather than one wait(SCAN_TIMEOUT_SECONDS), so a quit
        # in the middle of a long scan is noticed within a second.
        for _ in range(SCAN_TIMEOUT_SECONDS):
            if _cancel_event.is_set():
                break
            try:
                returncode = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                continue
            logger.info("Defender scan of %s finished with return code %s", self._save_path, returncode)
            return

        process.kill()
        reason = "the application is quitting" if _cancel_event.is_set() else f"no result after {SCAN_TIMEOUT_SECONDS} s"
        logger.warning("Defender scan of %s stopped: %s", self._save_path, reason)


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
        runnable = _ScanRunnable(_scan_target(record.save_path, record.name))
        QThreadPool.globalInstance().start(runnable)


def test_scan_target_follows_a_save_path_behind_a_junction(tmp_path):
    """save_path reached through a junction (or subst/mapped drive) must still
    narrow the scan to the torrent's folder, not fall back to the library."""
    from torrent2000.engine.antivirus_scan_service import _scan_target

    (tmp_path / "real" / "My.Torrent").mkdir(parents=True)
    link = tmp_path / "link"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(tmp_path / "real")], capture_output=True)
    if made.returncode != 0:
        pytest.skip("cannot create a junction here")

    assert _scan_target(str(link), "My.Torrent") == str(link / "My.Torrent")
