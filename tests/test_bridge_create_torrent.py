"""Coverage for CreateTorrentBridge: piece hashing runs on a worker thread
(never inside the QWebChannel slot), one job at a time, and the result comes
back through the `finished` signal."""

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from torrent2000.engine.torrent_creator import create_torrent_file
from torrent2000.ui.web import bridge_create_torrent
from torrent2000.ui.web.bridge_create_torrent import CreateTorrentBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def test_create_torrent_hashes_off_the_gui_thread_and_reports_through_finished(qapp, tmp_path, monkeypatch):
    source = tmp_path / "src.bin"
    source.write_bytes(b"x" * 50000)
    output = tmp_path / "out.torrent"

    calls = []

    def spy(*args, **kwargs):
        calls.append(threading.current_thread() is threading.main_thread())
        return create_torrent_file(*args, **kwargs)

    monkeypatch.setattr(bridge_create_torrent, "create_torrent_file", spy)

    bridge = CreateTorrentBridge()
    results = []
    bridge.finished.connect(results.append)

    assert bridge.createTorrent(str(source), str(output), [], False, "") is True
    # A second click while the first job is still running is refused, not queued.
    assert bridge.createTorrent(str(source), str(output), [], False, "") is False

    _wait(qapp, lambda: results)

    assert results == [{"ok": True, "path": str(output)}]
    assert lt.torrent_info(str(output)).num_files() == 1
    assert calls == [False]
    # The lock is released once the job has reported back.
    assert bridge.createTorrent(str(source), str(output), [], False, "") is True
    _wait(qapp, lambda: len(results) == 2)
    assert len(results) == 2


def test_quitting_cancels_a_running_job_without_reporting(qapp, tmp_path, caplog):
    source = tmp_path / "src.bin"
    source.write_bytes(b"x" * 50000)
    output = tmp_path / "out.torrent"

    bridge = CreateTorrentBridge()
    results = []
    bridge.finished.connect(results.append)
    bridge._cancel.set()  # what aboutToQuit does

    assert bridge.createTorrent(str(source), str(output), [], False, "") is True
    assert QThreadPool.globalInstance().waitForDone(10000)
    qapp.processEvents()

    assert results == []
    assert not output.exists()
    assert "dropped at quit" in caplog.text
