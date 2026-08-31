"""Coverage for KnownDiskBridge's category-move executor (the "disque connu"
action executor): previewCategoryMove()/executeCategoryMove() match
SessionManager records by category (case-insensitive, trimmed) and move them
under "<mountpoint>/<category>" via SessionManager.move_storage -- and a
failure moving one torrent must not block the others. Mirrors
test_known_disk_service.py's fixtures (QApplication offscreen, isolated data
dir for KnownDiskStore's JSON persistence)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.known_disk_service import KnownDiskService, KnownDiskStore
from torrent2000.engine.torrent_item import TorrentRecord
from torrent2000.ui.web.bridge_known_disk import KnownDiskBridge, _matching_records


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class FakeSessionManager:
    """Stand-in for engine.session_manager.SessionManager: only the two
    methods the bridge actually calls."""

    def __init__(self, records):
        self._records = records
        self.moved: list[tuple[str, str]] = []
        self.fail_for: set[str] = set()

    def all_records(self):
        return self._records

    def move_storage(self, info_hash: str, new_path: str) -> None:
        if info_hash in self.fail_for:
            raise RuntimeError("boom")
        self.moved.append((info_hash, new_path))


def _bridge(session_manager) -> KnownDiskBridge:
    store = KnownDiskStore()
    service = KnownDiskService(store, Settings())
    return KnownDiskBridge(store, service, session_manager)


def test_matching_records_is_case_insensitive_and_trims():
    films = TorrentRecord(info_hash="h1", category="Films")
    other = TorrentRecord(info_hash="h2", category="Musique")
    session_manager = FakeSessionManager([films, other])
    assert _matching_records(session_manager, "  films  ") == [films]
    assert _matching_records(session_manager, "FILMS") == [films]
    assert _matching_records(session_manager, "musique") == [other]
    assert _matching_records(session_manager, "livres") == []


def test_preview_counts_matching_records_and_sums_size():
    films1 = TorrentRecord(info_hash="h1", category="Films", total_size=1000)
    films2 = TorrentRecord(info_hash="h2", category="films", total_size=2000)
    other = TorrentRecord(info_hash="h3", category="Musique", total_size=500)
    bridge = _bridge(FakeSessionManager([films1, films2, other]))

    result = bridge.previewCategoryMove("Films")
    assert result == {"count": 2, "totalSize": 3000}


def test_preview_is_empty_for_unmatched_category():
    bridge = _bridge(FakeSessionManager([TorrentRecord(info_hash="h1", category="Films")]))
    assert bridge.previewCategoryMove("Musique") == {"count": 0, "totalSize": 0}


def test_execute_moves_each_matching_record_under_mountpoint_category():
    films1 = TorrentRecord(info_hash="h1", category="Films")
    films2 = TorrentRecord(info_hash="h2", category="Films")
    session_manager = FakeSessionManager([films1, films2])
    bridge = _bridge(session_manager)

    result = bridge.executeCategoryMove("Films", "D:\\Backup")

    assert result["moved"] == 2
    assert result["errors"] == []
    assert set(session_manager.moved) == {
        ("h1", os.path.join("D:\\Backup", "Films")),
        ("h2", os.path.join("D:\\Backup", "Films")),
    }


def test_execute_one_failure_does_not_block_the_others():
    films1 = TorrentRecord(info_hash="h1", name="Movie One", category="Films")
    films2 = TorrentRecord(info_hash="h2", name="Movie Two", category="Films")
    session_manager = FakeSessionManager([films1, films2])
    session_manager.fail_for = {"h1"}
    bridge = _bridge(session_manager)

    result = bridge.executeCategoryMove("Films", "D:\\Backup")

    assert result["moved"] == 1
    assert len(result["errors"]) == 1
    assert "Movie One" in result["errors"][0]
    assert session_manager.moved == [("h2", os.path.join("D:\\Backup", "Films"))]


def test_execute_does_nothing_for_unmatched_category():
    session_manager = FakeSessionManager([TorrentRecord(info_hash="h1", category="Films")])
    bridge = _bridge(session_manager)

    result = bridge.executeCategoryMove("Musique", "D:\\Backup")

    assert result == {"moved": 0, "errors": []}
    assert session_manager.moved == []
