"""QWebChannel bridge for the post-start file inclusion/exclusion editor --
mirrors ui/dialogs/file_priority_dialog.py. Every file starts checked in the
UI (SessionManager doesn't expose per-file priorities for reading, only
get_torrent_files(), which has no priority field); saveFilePriorities()
writes whatever the user leaves unchecked as the new full exclusion set via
set_file_priorities(), which also re-includes anything re-checked."""

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.session_manager import SessionManager


class FilePriorityBridge(QObject):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager

    @Slot(str, result="QVariantList")
    def getFiles(self, info_hash: str) -> list:
        # [] if no handle, or metadata not received yet (magnet still resolving).
        files = self._session_manager.get_torrent_files(info_hash)
        return [{"index": e.index, "path": e.path, "size": e.size} for e in files]

    @Slot(str, "QVariantList")
    def saveFilePriorities(self, info_hash: str, excluded_indices) -> None:
        excluded = {int(i) for i in excluded_indices}
        self._session_manager.set_file_priorities(info_hash, excluded)
