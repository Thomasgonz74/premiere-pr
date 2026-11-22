"""QWebChannel bridge for native file/folder pickers -- QFileDialog has no
web equivalent, so JS triggers a slot, Python shows the native dialog (blocks
inside the slot call, same as any modal QDialog), and the chosen path (or ""
on cancel) comes back through the slot's own return value, exactly like
DownloadsBridge.listTorrents() already does for its JS callback.
"""

import logging

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

logger = logging.getLogger(__name__)


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
        # Used by the Search page for a result link that isn't a .torrent
        # (see SearchBridge.fetchTorrent). The link comes from a third-party
        # feed: only a web page may open. openUrl hands anything else
        # (file:, a UNC path, search-ms:, ms-settings:...) to ShellExecute,
        # which can run a program.
        qurl = QUrl(url)
        if qurl.scheme() not in ("http", "https"):
            logger.warning("Refusing to open a %r link from a search result", qurl.scheme())
            return
        QDesktopServices.openUrl(qurl)
