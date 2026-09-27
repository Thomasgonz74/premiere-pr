"""Coverage for PostCompleteActionService: applies a routing rule's optional
move/unzip action once a torrent finishes, looked up via
TorrentRecord.matched_rule_name (see engine/post_complete_action_service.py).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import zipfile

import pytest
from PySide6.QtCore import QObject, Signal
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

    assert (tmp_path / "inner.txt").read_text(encoding="utf-8") == "hello world"


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
