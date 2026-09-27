"""QWebChannel bridge backing the Search page (catalogue idea "recherche de
torrents integree"). Source CRUD is synchronous (rare, deliberate user
actions, same convention as bridge_rss.py's feed CRUD); the actual search
runs on a QThreadPool worker (see engine/torrent_search_service.search_all)
so a slow/unreachable source never blocks the GUI thread.
"""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from torrent2000.config.settings import Settings
from torrent2000.engine.torrent_search_service import TorrentSearchSource, TorrentSearchSourceStore, search_all


def _source_to_dict(source: TorrentSearchSource) -> dict:
    return {"name": source.name, "urlTemplate": source.url_template, "enabled": source.enabled}


class _SearchRunnable(QRunnable):
    def __init__(self, sources, query: str, proxy, signals: "_SearchSignals") -> None:
        super().__init__()
        self._sources = sources
        self._query = query
        self._proxy = proxy
        self._signals = signals

    def run(self) -> None:
        results = search_all(self._sources, self._query, proxy=self._proxy)
        self._signals.resultsReady.emit(results)


class _SearchSignals(QObject):
    resultsReady = Signal(list)


class SearchBridge(QObject):
    resultsReady = Signal("QVariantList")

    def __init__(self, source_store: TorrentSearchSourceStore, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._source_store = source_store
        self._settings = settings
        self._signals = _SearchSignals()
        self._signals.resultsReady.connect(self.resultsReady.emit)

    @Slot(result="QVariantList")
    def listSources(self) -> list:
        return [_source_to_dict(s) for s in self._source_store.list_sources()]

    @Slot(str, str, bool)
    def saveSource(self, name: str, url_template: str, enabled: bool) -> None:
        name = name.strip()
        if not name:
            return
        self._source_store.save_source(
            TorrentSearchSource(name=name, url_template=url_template.strip(), enabled=enabled)
        )

    @Slot(str)
    def deleteSource(self, name: str) -> None:
        self._source_store.delete(name)

    @Slot(str)
    def search(self, query: str) -> None:
        query = query.strip()
        if not query:
            self.resultsReady.emit([])
            return
        runnable = _SearchRunnable(
            self._source_store.list_sources(), query, self._settings.proxy, self._signals
        )
        QThreadPool.globalInstance().start(runnable)
