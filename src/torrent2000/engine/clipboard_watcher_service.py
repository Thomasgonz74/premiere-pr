"""Clipboard magnet-link detection (catalogue idea) -- watches the system
clipboard and emits magnetDetected whenever a copied magnet: link is seen,
so the UI can OFFER to add it (never auto-adds silently -- a clipboard can
easily contain something copied for an unrelated reason a moment later).

OFF BY DEFAULT (Settings.clipboard_magnet_detection_enabled), same
opt-in-only convention as this project's other automations -- passively
reading clipboard content on every copy is exactly the kind of thing that
should never happen without the user explicitly turning it on.
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings


class ClipboardWatcherService(QObject):
    magnetDetected = Signal(str)  # the magnet: URI found

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._last_seen = ""
        clipboard = QApplication.clipboard()
        clipboard.dataChanged.connect(self._on_clipboard_changed)

    def _on_clipboard_changed(self) -> None:
        if not self._settings.clipboard_magnet_detection_enabled:
            return
        text = QApplication.clipboard().text().strip()
        if not text or text == self._last_seen:
            return
        self._last_seen = text
        if text.startswith("magnet:"):
            self.magnetDetected.emit(text)
