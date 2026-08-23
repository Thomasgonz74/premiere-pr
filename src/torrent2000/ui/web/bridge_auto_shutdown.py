"""QWebChannel bridge for AutoShutdownService -- forwards the countdown-
started signal to JS and exposes the cancel action, same forwarding pattern
as RssBridge (engine signal connected straight to a bridge-owned Signal)."""

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.engine.auto_shutdown_service import AutoShutdownService


class AutoShutdownBridge(QObject):
    countdownStarted = Signal(int)  # delay in seconds

    def __init__(self, auto_shutdown_service: AutoShutdownService, parent=None) -> None:
        super().__init__(parent)
        self._service = auto_shutdown_service
        auto_shutdown_service.shutdown_countdown_started.connect(self.countdownStarted.emit)

    @Slot()
    def cancelShutdown(self) -> None:
        self._service.cancel_shutdown()
