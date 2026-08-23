"""QWebChannel bridge for native file/folder pickers -- QFileDialog has no
web equivalent, so JS triggers a slot, Python shows the native dialog (blocks
inside the slot call, same as any modal QDialog), and the chosen path (or ""
on cancel) comes back through the slot's own return value, exactly like
DownloadsBridge.listTorrents() already does for its JS callback.
"""

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QFileDialog


class DialogBridge(QObject):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self._window = window

    @Slot(result=str)
    def browseTorrentFile(self) -> str:
        path, _filter = QFileDialog.getOpenFileName(
            self._window, "Choisir un fichier .torrent", "", "Torrent (*.torrent)"
        )
        return path

    @Slot(str, result=str)
    def browseFolder(self, current_path: str) -> str:
        return QFileDialog.getExistingDirectory(self._window, "Choisir un dossier", current_path or "")

    @Slot(str, str, result=str)
    def browseSaveFile(self, default_name: str, filter_str: str) -> str:
        path, _filter = QFileDialog.getSaveFileName(self._window, "Enregistrer sous", default_name, filter_str)
        return path

    @Slot(str, result=str)
    def browseOpenFile(self, filter_str: str) -> str:
        path, _filter = QFileDialog.getOpenFileName(self._window, "Choisir un fichier", "", filter_str)
        return path
