"""Peer list table for a single torrent -- IP/client/progress/speed per
connected peer. Unlike downloads_tab.py's torrent tables (which patch cells
in place via _set_text_if_changed to avoid flicker), a peer swarm's
membership turns over completely between polls, so refresh() just rebuilds
every row from scratch each call.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from torrent2000.engine.torrent_item import PeerInfo
from torrent2000.i18n.translator import tr
from torrent2000.utils.formatting import human_percent, human_rate

_COLUMN_COUNT = 5


def _columns() -> list[str]:
    return [
        tr("peer_list.column_ip"),
        tr("peer_list.column_client"),
        tr("peer_list.column_progress"),
        tr("peer_list.column_down_speed"),
        tr("peer_list.column_up_speed"),
    ]


class PeerListTable(QTableWidget):
    """Read-only IP/client/progress/speed table for one torrent's peers."""

    def __init__(self, parent=None) -> None:
        super().__init__(0, _COLUMN_COUNT, parent)
        self.setHorizontalHeaderLabels(_columns())
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def retranslate_ui(self) -> None:
        self.setHorizontalHeaderLabels(_columns())

    def refresh(self, peers: list[PeerInfo]) -> None:
        self.clearSpans()
        if not peers:
            # A silently empty table reads as "still loading" or "broken" --
            # a spanning message row makes the zero-peers state explicit.
            self.setRowCount(1)
            message_item = QTableWidgetItem(tr("peer_list.no_peers"))
            message_item.setTextAlignment(Qt.AlignCenter)
            message_item.setFlags(Qt.ItemIsEnabled)
            self.setItem(0, 0, message_item)
            self.setSpan(0, 0, 1, _COLUMN_COUNT)
            return

        self.setRowCount(len(peers))
        for row, peer in enumerate(peers):
            self.setItem(row, 0, QTableWidgetItem(peer.ip))
            self.setItem(row, 1, QTableWidgetItem(peer.client))
            self.setItem(row, 2, QTableWidgetItem(human_percent(peer.progress)))
            self.setItem(row, 3, QTableWidgetItem(human_rate(peer.down_speed)))
            self.setItem(row, 4, QTableWidgetItem(human_rate(peer.up_speed)))
