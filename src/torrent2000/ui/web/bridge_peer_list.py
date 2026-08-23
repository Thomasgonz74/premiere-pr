"""QWebChannel bridge exposing live per-peer info for one torrent.

Mirrors PeerListDialog/PeerListTable: the page polls getPeers on its own
2s timer while the dialog is open, this bridge just answers each call --
no push signal, no server-side timer to manage.
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.session_manager import SessionManager


class PeerListBridge(QObject):
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
