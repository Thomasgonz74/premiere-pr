"""Applies a routing rule's optional post-completion action (catalogue idea
"action de fin de telechargement personnalisable") once a torrent finishes:
move the finished files elsewhere, or unzip any .zip files found among them.

Deliberately NOT arbitrary command execution -- see
routing_rules.RoutingRule.post_complete_action's own docstring for why only
a closed set of safe, local file operations is supported.

Event-driven (SessionManager.torrent_finished), same pattern as
AntivirusScanService -- no QTimer of its own. Only ever looks at
TorrentRecord.matched_rule_name, set by the fully-automatic add paths
(watch folder, RSS) -- a manually-added torrent never has one, so this
service is simply a no-op for it.
"""

import logging
import threading
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from torrent2000.engine.routing_rules import RoutingRuleStore
from torrent2000.engine.session_manager import SessionManager

logger = logging.getLogger(__name__)


# Set once at quit: Qt waits for every running pool task before the process
# exits, so a multi-GB extraction would keep a windowless process alive for
# minutes. Checked before each member and before each chunk read from the
# archive, so even a single huge member stops within one chunk.
_cancel_event = threading.Event()


def cancel_running_extractions() -> None:
    """Called once at quit: a running extraction stops at its next chunk."""
    _cancel_event.set()


class _Cancelled(Exception):
    pass


class _CancellableReader:
    """A member's source stream that stops reading once quitting.
    ZipFile._extract_member copies it with shutil.copyfileobj (1 MiB
    chunks on Windows), so this is checked once per chunk."""

    def __init__(self, stream) -> None:
        self._stream = stream

    def read(self, n: int = -1) -> bytes:
        if _cancel_event.is_set():
            raise _Cancelled
        return self._stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self._stream.close()


class _CancellableZipFile(zipfile.ZipFile):
    # Only the source stream is wrapped: extract() itself -- and its member
    # path sanitizing -- stays zipfile's own.
    def open(self, name, mode="r", pwd=None, **kwargs):
        stream = super().open(name, mode, pwd, **kwargs)
        return _CancellableReader(stream) if mode == "r" else stream


class _UnzipSignals(QObject):
    finished = Signal()


class _UnzipRunnable(QRunnable):
    """Extracts off the GUI thread (648 ms measured for 200 MB on NVMe,
    minutes for multi-GB archives on an external disk), then reports back
    through signals.finished, which is queued to the GUI thread."""

    def __init__(self, zip_paths: list[Path], info_hash: str, signals: _UnzipSignals) -> None:
        super().__init__()
        self._zip_paths = zip_paths
        self._info_hash = info_hash
        self.signals = signals

    def run(self) -> None:
        try:
            for zip_path in self._zip_paths:
                try:
                    with _CancellableZipFile(zip_path) as zf:
                        for member in zf.infolist():
                            if _cancel_event.is_set():
                                raise _Cancelled
                            zf.extract(member, zip_path.parent)
                except _Cancelled:
                    logger.warning(
                        "Post-complete unzip of %s stopped at quit; the last extracted file may be incomplete",
                        zip_path,
                    )
                    return
                # NotImplementedError: unsupported method (Deflate64);
                # RuntimeError: encrypted member, password required.
                except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError):
                    logger.exception("Post-complete unzip failed for %s (info_hash=%s)", zip_path, self._info_hash)
        finally:
            # Quitting: nobody waits for this any more, and PySide's teardown
            # may already have deleted the signals object.
            if not _cancel_event.is_set():
                try:
                    self.signals.finished.emit()
                except RuntimeError:
                    pass  # deleted by PySide's teardown after the app quit


class PostCompleteActionService(QObject):
    # Emitted on the GUI thread when the last running extraction ends --
    # AutoShutdownService waits for it before starting its countdown.
    extractions_idle = Signal()

    def __init__(
        self, session_manager: SessionManager, routing_rule_store: RoutingRuleStore, parent=None
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._routing_rule_store = routing_rule_store
        self._pending_extractions = 0
        session_manager.torrent_finished.connect(self._on_torrent_finished)

    def has_pending_extractions(self) -> bool:
        return self._pending_extractions > 0

    def _on_torrent_finished(self, info_hash: str) -> None:
        record = self._session_manager.get_record(info_hash)
        if record is None or not record.matched_rule_name:
            return
        rule = next(
            (r for r in self._routing_rule_store.list_rules() if r.name == record.matched_rule_name), None
        )
        if rule is None or rule.post_complete_action == "none":
            return
        if rule.post_complete_action == "move" and rule.post_complete_move_to:
            self._session_manager.move_storage(info_hash, rule.post_complete_move_to)
        elif rule.post_complete_action == "unzip":
            self._unzip_files(record.save_path, info_hash)

    def _unzip_files(self, save_path: str, info_hash: str) -> None:
        # The file list is read here, on the GUI thread (it goes through the
        # libtorrent handle); only the extraction itself moves to the pool.
        zip_paths = [
            Path(save_path) / entry.path
            for entry in self._session_manager.get_torrent_files(info_hash)
            if entry.path.lower().endswith(".zip")
        ]
        if zip_paths:
            signals = _UnzipSignals(self)
            signals.finished.connect(self._on_extraction_finished)
            self._pending_extractions += 1
            QThreadPool.globalInstance().start(_UnzipRunnable(zip_paths, info_hash, signals))

    def _on_extraction_finished(self) -> None:
        self.sender().deleteLater()
        self._pending_extractions -= 1
        # Not once quitting: this can still be delivered by the quit's event
        # pumping, and must not start an auto-shutdown countdown then.
        if self._pending_extractions == 0 and not _cancel_event.is_set():
            self.extractions_idle.emit()
