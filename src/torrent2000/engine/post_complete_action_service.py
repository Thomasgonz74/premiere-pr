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
# minutes. Members are extracted one by one and the loop stops at the next.
_cancel_event = threading.Event()


def cancel_running_extractions() -> None:
    """Called once at quit: a running extraction stops after its current member."""
    _cancel_event.set()


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
                    with zipfile.ZipFile(zip_path) as zf:
                        for member in zf.infolist():
                            if _cancel_event.is_set():
                                logger.warning("Post-complete unzip of %s stopped at quit", zip_path)
                                return
                            zf.extract(member, zip_path.parent)
                except (OSError, zipfile.BadZipFile):
                    logger.exception("Post-complete unzip failed for %s (info_hash=%s)", zip_path, self._info_hash)
        finally:
            self.signals.finished.emit()


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
        if self._pending_extractions == 0:
            self.extractions_idle.emit()
