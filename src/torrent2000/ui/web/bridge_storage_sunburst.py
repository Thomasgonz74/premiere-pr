"""QWebChannel bridge exposing per-file size/completion breakdown for the
storage sunburst dialog.

Mirrors bridge_piece_map.py/bridge_swarm_constellation.py: reads
session_manager directly for its own dialog (one bridge per dialog, same as
PieceMapBridge vs PeerListBridge) rather than reusing window.bridge.
filePriority from JS -- FilePriorityBridge exposes size/path but not
per-file download progress, which this dialog needs for its color coding.
The page polls this on its own timer while the dialog is open and redraws
its own canvas -- no push signal, no server-side timer to manage.
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.session_manager import SessionManager


class StorageSunburstBridge(QObject):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager

    @Slot(str, result="QVariantList")
    def getFileBreakdown(self, info_hash: str) -> list:
        return self._session_manager.get_file_progress(info_hash)
