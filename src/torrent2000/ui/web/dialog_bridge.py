"""QWebChannel bridge for native file/folder pickers -- QFileDialog has no
web equivalent, so JS triggers a slot, Python shows the native dialog (blocks
inside the slot call, same as any modal QDialog), and the chosen path (or ""
on cancel) comes back through the slot's own return value, exactly like
DownloadsBridge.listTorrents() already does for its JS callback.
"""

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices
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

    @Slot(str)
    def openExternalUrl(self, url: str) -> None:
        # Used by the Search page for non-magnet (http/https) results --
        # AddBridge.selectTorrentFile() needs a local path, not a remote
        # URL, so these are handed to the user's default browser instead of
        # being fetched/added directly (out of scope: a download-then-add
        # pipeline for arbitrary third-party search results).
        QDesktopServices.openUrl(QUrl(url))
