"""Coverage for PostCompleteActionService: applies a routing rule's optional
move/unzip action once a torrent finishes, looked up via
TorrentRecord.matched_rule_name (see engine/post_complete_action_service.py).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import logging
import shutil
import threading
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import QApplication

from torrent2000.danger_scanner.models import FileEntry
from torrent2000.engine.post_complete_action_service import PostCompleteActionService
from torrent2000.engine.routing_rules import RoutingRule, RoutingRuleStore
from torrent2000.engine.torrent_item import TorrentRecord


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class FakeSessionManager(QObject):
    torrent_finished = Signal(str)

    def __init__(self):
        super().__init__()
        self.records = {}
        self.files = {}
        self.move_storage_calls = []

    def get_record(self, info_hash):
        return self.records.get(info_hash)

    def get_torrent_files(self, info_hash):
        return self.files.get(info_hash, [])

    def move_storage(self, info_hash, new_path):
        self.move_storage_calls.append((info_hash, new_path))


def test_move_action_calls_move_storage_with_the_rules_destination():
    RoutingRuleStore().save_rule(
        RoutingRule(
            name="linux", pattern="ubuntu", match_field="name", destination="D:/linux",
            post_complete_action="move", post_complete_move_to="E:/archive",
        )
    )
    session_manager = FakeSessionManager()
    session_manager.records["hash1"] = TorrentRecord(info_hash="hash1", save_path="D:/linux", matched_rule_name="linux")
    _service = PostCompleteActionService(session_manager, RoutingRuleStore())

    session_manager.torrent_finished.emit("hash1")

    assert session_manager.move_storage_calls == [("hash1", "E:/archive")]


def test_unzip_action_extracts_zip_files_found_among_the_torrents_files(tmp_path):
    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("inner.txt", "hello world")

    RoutingRuleStore().save_rule(
        RoutingRule(
            name="software", pattern="setup", match_field="name", destination=str(tmp_path),
            post_complete_action="unzip",
        )
    )
    session_manager = FakeSessionManager()
    session_manager.records["hash2"] = TorrentRecord(
        info_hash="hash2", save_path=str(tmp_path), matched_rule_name="software"
    )
    session_manager.files["hash2"] = [FileEntry(index=0, path="pack.zip", size=zip_path.stat().st_size)]
    _service = PostCompleteActionService(session_manager, RoutingRuleStore())

    session_manager.torrent_finished.emit("hash2")
    QThreadPool.globalInstance().waitForDone()  # extraction runs on the pool

    assert (tmp_path / "inner.txt").read_text(encoding="utf-8") == "hello world"


def test_unzip_is_handed_to_the_thread_pool_not_run_on_the_gui_thread(tmp_path):
    """Extraction can take minutes on multi-GB archives -- the torrent_finished
    slot must only collect the zip list and queue a runnable."""
    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("inner.txt", "hello world")
    RoutingRuleStore().save_rule(
        RoutingRule(
            name="software", pattern="setup", match_field="name", destination=str(tmp_path),
            post_complete_action="unzip",
        )
    )
    session_manager = FakeSessionManager()
    session_manager.records["hash5"] = TorrentRecord(
        info_hash="hash5", save_path=str(tmp_path), matched_rule_name="software"
    )
    session_manager.files["hash5"] = [
        FileEntry(index=0, path="pack.zip", size=zip_path.stat().st_size),
        FileEntry(index=1, path="readme.txt", size=1),
    ]
    _service = PostCompleteActionService(session_manager, RoutingRuleStore())

    mock_start = MagicMock()
    with patch("torrent2000.engine.post_complete_action_service.QThreadPool") as mock_pool_cls:
        mock_pool_cls.globalInstance.return_value.start = mock_start
        session_manager.torrent_finished.emit("hash5")

    assert not (tmp_path / "inner.txt").exists()  # nothing extracted synchronously
    mock_start.assert_called_once()
    assert mock_start.call_args[0][0]._zip_paths == [zip_path]


def test_no_action_when_torrent_has_no_matched_rule():
    session_manager = FakeSessionManager()
    session_manager.records["hash3"] = TorrentRecord(info_hash="hash3", save_path="D:/x", matched_rule_name=None)
    _service = PostCompleteActionService(session_manager, RoutingRuleStore())

    session_manager.torrent_finished.emit("hash3")  # must not raise

    assert session_manager.move_storage_calls == []


def test_no_action_when_matched_rule_has_action_none():
    RoutingRuleStore().save_rule(
        RoutingRule(name="linux", pattern="ubuntu", match_field="name", destination="D:/linux")
    )
    session_manager = FakeSessionManager()
    session_manager.records["hash4"] = TorrentRecord(info_hash="hash4", save_path="D:/linux", matched_rule_name="linux")
    _service = PostCompleteActionService(session_manager, RoutingRuleStore())

    session_manager.torrent_finished.emit("hash4")

    assert session_manager.move_storage_calls == []


def test_unknown_info_hash_is_a_noop():
    session_manager = FakeSessionManager()
    _service = PostCompleteActionService(session_manager, RoutingRuleStore())

    session_manager.torrent_finished.emit("unknown")  # must not raise


def _unzip_rule_and_session(tmp_path, info_hash):
    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.txt", "a")
        zf.writestr("b.txt", "b")
    RoutingRuleStore().save_rule(
        RoutingRule(
            name="software", pattern="setup", match_field="name", destination=str(tmp_path),
            post_complete_action="unzip",
        )
    )
    session_manager = FakeSessionManager()
    session_manager.records[info_hash] = TorrentRecord(
        info_hash=info_hash, save_path=str(tmp_path), matched_rule_name="software"
    )
    session_manager.files[info_hash] = [FileEntry(index=0, path="pack.zip", size=zip_path.stat().st_size)]
    return session_manager


def test_pending_extraction_is_reported_until_the_runnable_finishes(tmp_path, qapp):
    """AutoShutdownService relies on this to never shut down mid-extraction."""
    session_manager = _unzip_rule_and_session(tmp_path, "hash6")
    service = PostCompleteActionService(session_manager, RoutingRuleStore())
    idle = []
    service.extractions_idle.connect(lambda: idle.append(True))

    session_manager.torrent_finished.emit("hash6")
    assert service.has_pending_extractions()

    QThreadPool.globalInstance().waitForDone()
    qapp.processEvents()  # the finished signal is queued to this thread

    assert not service.has_pending_extractions()
    assert idle == [True]
    assert (tmp_path / "b.txt").exists()


def test_extraction_stops_once_cancelled_at_quit(tmp_path):
    from torrent2000.engine import post_complete_action_service as pca

    zip_path = tmp_path / "pack.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.txt", "a")
    signals = pca._UnzipSignals()
    finished = []
    signals.finished.connect(lambda: finished.append(True))
    pca.cancel_running_extractions()
    try:
        pca._UnzipRunnable([zip_path], "hash7", signals).run()
    finally:
        pca._cancel_event.clear()

    assert not (tmp_path / "a.txt").exists()
    # Not reported: nothing waits for it once quitting, and PySide's teardown
    # may already have deleted the signals object.
    assert finished == []


def test_an_extraction_reporting_back_during_quit_is_not_idle(tmp_path, qapp, monkeypatch):
    """The finished signal can be delivered by the quit's own event pumping
    (SessionManager.shutdown) -- extractions_idle then would let
    AutoShutdownService start its countdown mid-quit."""
    from torrent2000.engine import post_complete_action_service as pca

    monkeypatch.setattr(pca, "_cancel_event", threading.Event())
    session_manager = _unzip_rule_and_session(tmp_path, "hash8")
    service = PostCompleteActionService(session_manager, RoutingRuleStore())
    idle = []
    service.extractions_idle.connect(lambda: idle.append(True))

    session_manager.torrent_finished.emit("hash8")
    QThreadPool.globalInstance().waitForDone()  # done, its signal still queued
    pca.cancel_running_extractions()  # Quit clicked before it is delivered
    qapp.processEvents()

    assert idle == []


def test_cancel_interrupts_a_single_huge_member(tmp_path, monkeypatch, caplog):
    """A lone multi-GB member (ISO, MKV) must not keep the quit waiting for
    its whole extraction: the source stream stops at its next chunk."""
    from torrent2000.engine import post_complete_action_service as pca

    zip_path = tmp_path / "movie.zip"
    member_size = 4 * shutil.COPY_BUFSIZE
    with zipfile.ZipFile(zip_path, "w") as zf:  # stored, so every chunk is a real read
        zf.writestr("movie.mkv", b"\0" * member_size)
    monkeypatch.setattr(pca, "_cancel_event", threading.Event())
    real_read = pca._CancellableReader.read

    def read_then_quit(self, n=-1):
        data = real_read(self, n)
        pca.cancel_running_extractions()  # Quit clicked during the first chunk
        return data

    monkeypatch.setattr(pca._CancellableReader, "read", read_then_quit)
    signals = pca._UnzipSignals()
    finished = []
    signals.finished.connect(lambda: finished.append(True))

    with caplog.at_level(logging.WARNING, logger=pca.__name__):
        pca._UnzipRunnable([zip_path], "hash9", signals).run()  # nothing escapes

    assert 0 < (tmp_path / "movie.mkv").stat().st_size < member_size
    assert "movie.zip" in caplog.text and "may be incomplete" in caplog.text
    assert finished == []
