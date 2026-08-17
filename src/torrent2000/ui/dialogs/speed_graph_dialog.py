"""Non-modal dialog hosting a SpeedGraphWidget for one torrent, refreshed
on a timer for as long as the dialog stays open.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout

from torrent2000.engine.session_manager import SessionManager
from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.speed_graph import SpeedGraphWidget

_REFRESH_INTERVAL_MS = 1000


class SpeedGraphDialog(QDialog):
    def __init__(self, session_manager: SessionManager, info_hash: str, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._info_hash = info_hash

        self.setWindowTitle(tr("speed_graph.dialog_title"))
        self.resize(480, 260)

        layout = QVBoxLayout(self)
        self.graph = SpeedGraphWidget(self)
        layout.addWidget(self.graph)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(_REFRESH_INTERVAL_MS)
        self._refresh()

    def _refresh(self) -> None:
        history = self._session_manager.get_speed_history(self._info_hash)
        self.graph.set_history(history)

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
