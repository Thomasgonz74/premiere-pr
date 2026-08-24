"""QWebChannel bridge exposing per-torrent piece availability to the web UI.

Mirrors bridge_peer_list.py/bridge_speed_graph.py: the page polls this on
its own timer while the dialog is open and redraws its own canvas -- no
push signal, no server-side timer to manage.
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.session_manager import SessionManager


class PieceMapBridge(QObject):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager

    @Slot(str, result="QVariantMap")
    def getPieceAvailability(self, info_hash: str) -> dict:
        data = self._session_manager.get_piece_availability(info_hash)
        return {
            "numPieces": data["num_pieces"],
            "have": data["have"],
            "availability": data["availability"],
        }
