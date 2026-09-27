"""Coverage for CreateTorrentBridge: piece hashing runs on a worker thread
(never inside the QWebChannel slot), one job at a time, and the result comes
back through the `finished` signal."""

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.ui.web.bridge_create_torrent import CreateTorrentBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_create_torrent_hashes_off_the_gui_thread_and_reports_through_finished(qapp, tmp_path, monkeypatch):
    source = tmp_path / "src.bin"
    source.write_bytes(b"x" * 50000)
    output = tmp_path / "out.torrent"

    real_set_piece_hashes = lt.set_piece_hashes
    calls = []

    def spy(*args):
        calls.append((threading.current_thread() is threading.main_thread(), len(args)))
        return real_set_piece_hashes(*args)

    monkeypatch.setattr(lt, "set_piece_hashes", spy)

    bridge = CreateTorrentBridge()
    results = []
    bridge.finished.connect(results.append)

    assert bridge.createTorrent(str(source), str(output), [], False, "") is True
    # A second click while the first job is still running is refused, not queued.
    assert bridge.createTorrent(str(source), str(output), [], False, "") is False

    deadline = time.monotonic() + 10
    while not results and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert results == [{"ok": True, "path": str(output)}]
    assert lt.torrent_info(str(output)).num_files() == 1
    # Worker thread, and the per-piece-callback overload: the plain
    # set_piece_hashes(ct, path) holds the GIL and would still freeze the GUI.
    assert calls == [(False, 3)]
    # The lock is released once the job has reported back.
    assert bridge.createTorrent(str(source), str(output), [], False, "") is True
    deadline = time.monotonic() + 10
    while len(results) < 2 and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert len(results) == 2
