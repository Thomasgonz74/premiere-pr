"""QWebChannel bridge exposing live per-peer info for one torrent.

Mirrors PeerListDialog/PeerListTable: the page polls getPeers on its own
2s timer while the dialog is open, this bridge just answers each call --
no push signal, no server-side timer to manage.
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager


class PeerListBridge(QObject):
    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings

    @Slot(str, result="QVariantList")
    def getPeers(self, info_hash: str) -> list:
        peers = self._session_manager.get_peer_info(info_hash)
        reputation_enabled = self._settings.peer_reputation_enabled
        result = []
        for p in peers:
            entry = {
                "ip": p.ip,
                "client": p.client,
                "progress": p.progress,
                "downSpeed": p.down_speed,
                "upSpeed": p.up_speed,
            }
            if reputation_enabled:
                # Folded in here (O(1) lookup, no extra effect) instead of a
                # separate getReputationScores() round-trip the page used to
                # make right after every getPeers() poll.
                entry["reputation"] = self._session_manager.get_peer_reputation_score(p.ip)
            result.append(entry)
        return result

    # Opt-in (see Settings.peer_reputation_enabled / engine/peer_reputation.py).
    @Slot(result=bool)
    def isReputationEnabled(self) -> bool:
        return self._settings.peer_reputation_enabled

    @Slot("QVariantList", result="QVariantMap")
    def getReputationScores(self, ips: list) -> dict:
        """ips: the "address:port" strings from a prior getPeers() call.
        Returns {ip: "good"|"neutral"|"bad"}."""
        if not self._settings.peer_reputation_enabled:
            return {}
        return {ip: self._session_manager.get_peer_reputation_score(ip) for ip in ips}
