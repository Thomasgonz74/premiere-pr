"""QWebChannel bridge for the post-start file inclusion/exclusion editor --
mirrors ui/dialogs/file_priority_dialog.py. Each file comes with its current
priority so the UI starts with excluded files unchecked; saveFilePriorities()
writes whatever the user leaves unchecked as the new full exclusion set via
set_file_priorities(), which also re-includes anything re-checked."""

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.session_manager import FILE_PRIORITY_DEFAULT, SessionManager


class FilePriorityBridge(QObject):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager

    @Slot(str, result="QVariantList")
    def getFiles(self, info_hash: str) -> list:
        # [] if no handle, or metadata not received yet (magnet still resolving).
        files = self._session_manager.get_torrent_files(info_hash)
        priorities = self._session_manager.get_file_priorities(info_hash)
        return [
            {
                "index": e.index,
                "path": e.path,
                "size": e.size,
                "priority": priorities[e.index] if e.index < len(priorities) else FILE_PRIORITY_DEFAULT,
            }
            for e in files
        ]

    @Slot(str, "QVariantList")
    def saveFilePriorities(self, info_hash: str, excluded_indices) -> None:
        excluded = {int(i) for i in excluded_indices}
        self._session_manager.set_file_priorities(info_hash, excluded)
