import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel

from torrent2000.i18n.translator import tr


class DropZoneWidget(QLabel):
    """Accepts a dragged-and-dropped .torrent file and reports its path."""

    torrent_file_dropped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setText(tr("add_tab.drop_zone"))
        self.setMinimumHeight(90)
        self.setObjectName("dropZone")

    def retranslate_ui(self) -> None:
        self.setText(tr("add_tab.drop_zone"))

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".torrent"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".torrent"):
                # toLocalFile() returns forward slashes on Windows; normalize
                # to native separators so a dropped path matches what
                # QFileDialog's Browse... would have produced.
                self.torrent_file_dropped.emit(os.path.normpath(path))
                event.acceptProposedAction()
                return
        event.ignore()
