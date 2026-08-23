"""QWebChannel bridge exposing per-torrent speed history to the web UI.

Mirrors ui/dialogs/speed_graph_dialog.py: the page polls this on a timer
and redraws its own canvas, instead of SpeedGraphDialog polling and handing
samples to SpeedGraphWidget.set_history().
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.session_manager import SessionManager


class SpeedGraphBridge(QObject):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager

    @Slot(str, result="QVariantList")
    def getSpeedHistory(self, info_hash: str) -> list:
        # QVariantList can't carry raw tuples cleanly -- flatten to 2-element lists.
        return [[down, up] for down, up in self._session_manager.get_speed_history(info_hash)]
