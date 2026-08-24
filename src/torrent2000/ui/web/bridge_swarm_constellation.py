"""QWebChannel bridge exposing live per-peer info for the swarm constellation
view of one torrent.

Mirrors bridge_peer_list.py exactly (same underlying session_manager call,
same field shape): the page polls this on its own timer while the dialog is
open and redraws its own canvas -- no push signal, no server-side timer to
manage. Kept as its own bridge/object (rather than reusing window.bridge.
peerList from JS) to follow the one-bridge-per-dialog pattern already used
throughout this codebase (see PieceMapBridge vs PeerListBridge, which also
both read session_manager independently for their own dialog).
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.session_manager import SessionManager


class SwarmConstellationBridge(QObject):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager

    @Slot(str, result="QVariantList")
    def getPeers(self, info_hash: str) -> list:
        peers = self._session_manager.get_peer_info(info_hash)
        return [
            {
                "ip": p.ip,
                "client": p.client,
                "progress": p.progress,
                "downSpeed": p.down_speed,
                "upSpeed": p.up_speed,
            }
            for p in peers
        ]
