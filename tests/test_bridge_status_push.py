"""Per-tick status pushes from DownloadsBridge/ShareBridge to the web page:
one recordsUpdated list per tick, nothing while the window is hidden or
minimized (set_live(False)), a single resync on hidden -> visible only, and
ShareBridge's "limit reached" push kept active while hidden.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.engine.share_limits import ShareLimit
from torrent2000.engine.torrent_item import TorrentRecord
from torrent2000.ui.web.bridge_downloads import DownloadsBridge
from torrent2000.ui.web.bridge_share import ShareBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeSessionManager(QObject):
    torrent_added = Signal(str)
    torrent_removed = Signal(str)
    torrent_restore_failed = Signal(str)
    torrent_status_batch_updated = Signal(list)
    ip_blocklist_wait_changed = Signal(bool)

    def __init__(self, records) -> None:
        super().__init__()
        self._records = {r.info_hash: r for r in records}

    def get_record(self, info_hash):
        return self._records.get(info_hash)

    def all_records(self):
        return list(self._records.values())


class _FakeShareLimitService(QObject):
    limit_reached = Signal(str, str)

    def __init__(self, tracked) -> None:
        super().__init__()
        self._limits = {ih: ShareLimit(None, None, None, started_at=0.0, uploaded_baseline=0) for ih in tracked}

    def is_tracked(self, info_hash):
        return info_hash in self._limits

    def limit_for(self, info_hash):
        return self._limits.get(info_hash)

    def tracked_info_hashes(self):
        return list(self._limits)

    def progress(self, info_hash, record):
        return 0.0, 0


def test_downloads_bridge_batches_ticks_and_resyncs_once_when_shown_again():
    records = [TorrentRecord(info_hash="h1"), TorrentRecord(info_hash="h2")]
    sm = _FakeSessionManager(records)
    bridge = DownloadsBridge(sm, bandwidth_scheduler=None)
    batches = []
    bridge.recordsUpdated.connect(batches.append)

    sm.torrent_status_batch_updated.emit(records)
    assert [[row["infoHash"] for row in batch] for batch in batches] == [["h1", "h2"]]

    bridge.set_live(True)  # startup show(): already live, nothing replayed
    bridge.set_live(False)  # hidden to the tray
    sm.torrent_status_batch_updated.emit(records)
    bridge.set_live(False)  # e.g. hideEvent + minimize changeEvent
    assert len(batches) == 1

    bridge.set_live(True)  # hidden -> visible: one resync of the current state
    bridge.set_live(True)
    assert [[row["infoHash"] for row in batch] for batch in batches] == [["h1", "h2"], ["h1", "h2"]]


def test_share_bridge_keeps_limit_reached_pushes_while_hidden():
    records = [TorrentRecord(info_hash="tracked"), TorrentRecord(info_hash="untracked")]
    sm = _FakeSessionManager(records)
    limits = _FakeShareLimitService(tracked=["tracked"])
    bridge = ShareBridge(sm, limits, settings=None)
    batches, single_pushes = [], []
    bridge.recordsUpdated.connect(batches.append)
    bridge.recordUpdated.connect(single_pushes.append)

    sm.torrent_status_batch_updated.emit(records)
    assert [[row["infoHash"] for row in batch] for batch in batches] == [["tracked"]]

    bridge.set_live(False)
    sm.torrent_status_batch_updated.emit(records)
    limits.limit_reached.emit("tracked", "time")

    assert len(batches) == 1
    assert [row["infoHash"] for row in single_pushes] == ["tracked"]
