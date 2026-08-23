"""QWebChannel bridge for the torrent-creation dialog -- a thin wrapper
around engine/torrent_creator.py's freestanding create_torrent_file(), not
bound to a SessionManager or any live torrent state (there's nothing to be
bound to before the .torrent file exists).
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.engine.torrent_creator import create_torrent_file


class CreateTorrentBridge(QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    @Slot(str, str, "QVariantList", bool, str, result="QVariantMap")
    def createTorrent(self, source_path: str, output_path: str, trackers, private: bool, comment: str) -> dict:
        try:
            create_torrent_file(source_path, output_path, list(trackers), private=private, comment=comment)
        except Exception:
            return {"ok": False, "error": "La création du torrent a échoué."}
        return {"ok": True}
