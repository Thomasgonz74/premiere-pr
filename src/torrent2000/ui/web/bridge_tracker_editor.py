"""QWebChannel bridge exposing the per-torrent tracker list editor.

Mirrors TrackerEditorWidget: add/remove a tracker on demand, no timers, no
automation tied to download progress. The page re-fetches the full list via
getTrackers after every add/remove (same "refresh()" pattern as the native
widget), so this bridge stays a thin pass-through to SessionManager.
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.session_manager import SessionManager


class TrackerEditorBridge(QObject):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager

    @Slot(str, result="QVariantList")
    def getTrackers(self, info_hash: str) -> list:
        trackers = self._session_manager.get_trackers(info_hash)
        return [{"url": t.url, "tier": t.tier, "lastError": t.last_error} for t in trackers]

    @Slot(str, str)
    def addTracker(self, info_hash: str, url: str) -> None:
        self._session_manager.add_tracker(info_hash, url)

    @Slot(str, str)
    def removeTracker(self, info_hash: str, url: str) -> None:
        self._session_manager.remove_tracker(info_hash, url)
