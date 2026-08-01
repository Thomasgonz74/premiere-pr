from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel


class DropZoneWidget(QLabel):
    """Accepts a dragged-and-dropped .torrent file and reports its path."""

    torrent_file_dropped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setText("Glissez-déposez un fichier .torrent ici")
        self.setMinimumHeight(90)
        self.setObjectName("dropZone")

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
                self.torrent_file_dropped.emit(path)
                event.acceptProposedAction()
                return
        event.ignore()
