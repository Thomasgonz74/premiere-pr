"""Non-modal peer list dialog for a single torrent -- IP/client/progress/
speed per connected peer, polled on its own timer while the dialog is open.

Not wired into the UI yet: downloads_tab.py's "Voir les pairs" context-menu
entry (a later phase) is what will construct and show() an instance of this
dialog.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout

from torrent2000.engine.session_manager import SessionManager
from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.peer_list_table import PeerListTable
from torrent2000.utils.qt_timers import start_periodic_timer

# A per-peer poll doesn't need the torrent list's own 300ms reactivity --
# peer churn is slow enough that 2s stays current without being wasteful.
_POLL_INTERVAL_MS = 2000


class PeerListDialog(QDialog):
    """Shows live peer details for one torrent. Non-modal so it can stay
    open alongside the main window; stops its own poll timer as soon as the
    dialog finishes (close button, or a programmatic accept/reject), rather
    than tying its lifetime to the torrent list's own polling."""

    def __init__(self, session_manager: SessionManager, info_hash: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("peer_list.window_title"))
        self.setModal(False)
        self._session_manager = session_manager
        self._info_hash = info_hash

        layout = QVBoxLayout(self)
        self.table = PeerListTable(self)
        layout.addWidget(self.table)

        self._timer = start_periodic_timer(self, _POLL_INTERVAL_MS, self._on_tick)
        self.finished.connect(self._on_finished)
        self._on_tick()  # populate right away instead of waiting a full interval

    def _on_tick(self) -> None:
        peers = self._session_manager.get_peer_info(self._info_hash)
        self.table.refresh(peers)

    def _on_finished(self, result: int = 0) -> None:
        self._timer.stop()
