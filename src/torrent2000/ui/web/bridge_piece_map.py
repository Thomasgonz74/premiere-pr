"""QWebChannel bridge exposing per-torrent piece availability to the web UI.

Mirrors bridge_peer_list.py/bridge_speed_graph.py: the page polls this on
its own timer while the dialog is open and redraws its own canvas -- no
push signal, no server-side timer to manage.
"""

from itertools import repeat

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.session_manager import SessionManager

_DIGITS = bytes.maketrans(bytes(range(10)), b"0123456789")


class PieceMapBridge(QObject):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager

    @Slot(str, result="QVariantMap")
    def getPieceAvailability(self, info_hash: str) -> dict:
        data = self._session_manager.get_piece_availability(info_hash)
        # Two compact strings, one char per piece, instead of two
        # num_pieces-long QVariantLists (17 ms + 300 KB of JSON per 2 s poll
        # at 40k pieces): have[i] is "1"/"0", availability[i] the peer count
        # capped at 9 (the map only tells 0 / 1-2 / 3+ apart). Decoded by
        # piece_map_dialog.js -- change both together.
        return {
            "numPieces": data["num_pieces"],
            "have": bytes(data["have"]).translate(_DIGITS).decode("ascii"),
            "availability": bytes(map(min, data["availability"], repeat(9))).translate(_DIGITS).decode("ascii"),
        }
