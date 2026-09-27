"""QWebChannel bridge for the torrent-creation dialog -- a thin wrapper
around engine/torrent_creator.py's freestanding create_torrent_file(), not
bound to a SessionManager or any live torrent state (there's nothing to be
bound to before the .torrent file exists).

Piece hashing reads the whole source (tens of seconds for a large folder),
so it runs on a QThreadPool worker and reports back through `finished`
(same QRunnable + signals pattern as bridge_search.py) instead of freezing
the GUI thread inside the slot. Quitting cancels it (aboutToQuit sets the
job's cancel event) instead of the process lingering until the hash ends.
"""

import logging
import threading

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, Signal, Slot

from torrent2000.engine.torrent_creator import CreationCancelled, create_torrent_file

logger = logging.getLogger(__name__)


class _CreateTorrentRunnable(QRunnable):
    def __init__(
        self, source_path, output_path, trackers, private, comment, signals: "_CreateTorrentSignals", cancel
    ) -> None:
        super().__init__()
        self._source_path = source_path
        self._output_path = output_path
        self._trackers = trackers
        self._private = private
        self._comment = comment
        self._signals = signals
        self._cancel = cancel

    def run(self) -> None:
        try:
            create_torrent_file(
                self._source_path,
                self._output_path,
                self._trackers,
                private=self._private,
                comment=self._comment,
                cancel=self._cancel,
            )
        except CreationCancelled:
            # Quitting: nothing was written, and the bridge may already be
            # gone, so no emit.
            logger.warning("Torrent creation for %s dropped at quit", self._source_path)
            return
        except Exception:
            logger.exception("Torrent creation failed for %s", self._source_path)
            result = {"ok": False, "path": self._output_path, "error": "La création du torrent a échoué."}
        else:
            result = {"ok": True, "path": self._output_path}
        if self._cancel.is_set():
            return  # finished just as the app quit: nobody is left to tell
        try:
            self._signals.finished.emit(result)
        except RuntimeError:
            pass  # signals object deleted by PySide's teardown after the app quit


class _CreateTorrentSignals(QObject):
    finished = Signal(dict)


class CreateTorrentBridge(QObject):
    finished = Signal("QVariantMap")  # {ok, path, error?}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._busy = False
        self._cancel = threading.Event()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._cancel.set)
        self._signals = _CreateTorrentSignals()
        self._signals.finished.connect(self._on_finished)

    @Slot(str, str, "QVariantList", bool, str, result=bool)
    def createTorrent(self, source_path: str, output_path: str, trackers, private: bool, comment: str) -> bool:
        """Starts hashing in the background; False if a creation is already
        running (double click, or a dialog reopened mid-hash) -- one at a
        time also keeps two jobs from racing on the same output .tmp file."""
        if self._busy:
            return False
        self._busy = True
        QThreadPool.globalInstance().start(
            _CreateTorrentRunnable(
                source_path, output_path, list(trackers), private, comment, self._signals, self._cancel
            )
        )
        return True

    def is_busy(self) -> bool:
        """True while a job hashes -- AutoShutdownService waits for `finished`."""
        return self._busy

    def _on_finished(self, result: dict) -> None:
        self._busy = False
        self.finished.emit(result)
