"""SearchBridge (ui/web/bridge_search.py) and the link opener the Search page
uses for a result that isn't a .torrent (DialogBridge.openExternalUrl)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.web import bridge_search, dialog_bridge
from torrent2000.ui.web.bridge_search import SearchBridge
from torrent2000.ui.web.dialog_bridge import DialogBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeStore:
    def list_sources(self):
        return []


class _CapturingPool:
    def __init__(self):
        self.started = []

    def start(self, runnable, priority=0):
        self.started.append(runnable)


def test_an_older_search_finishing_last_does_not_replace_the_newer_results(monkeypatch):
    pool = _CapturingPool()
    monkeypatch.setattr(bridge_search.QThreadPool, "globalInstance", staticmethod(lambda: pool))
    monkeypatch.setattr(bridge_search, "search_all", lambda sources, query, proxy=None: [{"title": query}])
    bridge = SearchBridge(_FakeStore(), Settings())
    shown = []
    bridge.resultsReady.connect(shown.append)

    bridge.search("old")
    bridge.search("new")
    pool.started[1].run()  # the newer search answers first...
    pool.started[0].run()  # ...then the slow older one

    assert shown == [[{"title": "new"}]]


@pytest.mark.parametrize(
    "link",
    [
        "file:///C:/Windows/System32/calc.exe",
        "file://attacker.example/share/payload.exe",
        "search-ms:query=x",
        "ms-settings:privacy",
    ],
)
def test_a_result_link_that_is_not_a_web_page_is_never_handed_to_the_shell(monkeypatch, link):
    opened = []
    monkeypatch.setattr(dialog_bridge.QDesktopServices, "openUrl", staticmethod(opened.append))

    DialogBridge(None).openExternalUrl(link)
    DialogBridge(None).openExternalUrl("https://indexer.example/details/1")

    assert [url.toString() for url in opened] == ["https://indexer.example/details/1"]
