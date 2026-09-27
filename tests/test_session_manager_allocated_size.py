"""Tests for SessionManager.get_allocated_size -- sums real on-disk allocated
bytes across a torrent's files, via disk_allocation.compressed_file_size.
Mocking pattern (bypass __init__, fake torrent_info) matches
test_session_manager_missing_features.py and test_torrent_files.py.
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord

_FLAG_PAD_FILE = 1


def _mock_torrent_info(entries: list[tuple[str, int]]) -> MagicMock:
    fs = MagicMock()
    fs.flag_pad_file = _FLAG_PAD_FILE
    fs.flag_hidden = 2
    fs.flag_executable = 4
    fs.num_files.return_value = len(entries)
    fs.file_path.side_effect = lambda i: entries[i][0]
    fs.file_size.side_effect = lambda i: entries[i][1]
    fs.file_flags.side_effect = lambda i: 0
    ti = MagicMock()
    ti.files.return_value = fs
    return ti


def _session_manager_with_handle(info_hash: str, save_path: str, handle) -> SessionManager:
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    sm._handles = {info_hash: handle}
    sm._records = {info_hash: TorrentRecord(info_hash=info_hash, save_path=save_path)}
    return sm


def test_sums_real_allocated_bytes_across_files(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    (tmp_path / "b.bin").write_bytes(b"y" * 250)
    handle = MagicMock()
    handle.torrent_file.return_value = _mock_torrent_info([("a.bin", 100), ("b.bin", 250)])
    sm = _session_manager_with_handle("hash1", str(tmp_path), handle)

    assert sm.get_allocated_size("hash1") == 350


def test_missing_file_on_disk_contributes_zero(tmp_path):
    (tmp_path / "downloaded.bin").write_bytes(b"z" * 42)
    handle = MagicMock()
    # "not_yet.bin" is listed in the torrent but hasn't been downloaded yet
    handle.torrent_file.return_value = _mock_torrent_info([("downloaded.bin", 42), ("not_yet.bin", 999)])
    sm = _session_manager_with_handle("hash1", str(tmp_path), handle)

    assert sm.get_allocated_size("hash1") == 42


def test_unknown_info_hash_returns_zero():
    sm = SessionManager.__new__(SessionManager)
    sm._handles = {}
    sm._records = {}

    assert sm.get_allocated_size("nope") == 0


def test_metadata_not_yet_available_returns_zero(tmp_path):
    handle = MagicMock()
    handle.torrent_file.return_value = None  # magnet still resolving
    sm = _session_manager_with_handle("hash1", str(tmp_path), handle)

    assert sm.get_allocated_size("hash1") == 0


def test_path_traversal_entry_is_excluded_from_the_sum(tmp_path):
    (tmp_path / "inside.bin").write_bytes(b"x" * 100)
    outside_dir = tmp_path.parent / "outside_confinement_test"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "escaped.bin").write_bytes(b"y" * 999)
    try:
        handle = MagicMock()
        # A torrent-internal path crafted with ../ segments to point outside
        # save_path -- see SessionManager._is_confined.
        escaped_relative = os.path.relpath(outside_dir / "escaped.bin", tmp_path)
        handle.torrent_file.return_value = _mock_torrent_info(
            [("inside.bin", 100), (escaped_relative, 999)]
        )
        sm = _session_manager_with_handle("hash1", str(tmp_path), handle)

        assert sm.get_allocated_size("hash1") == 100
    finally:
        (outside_dir / "escaped.bin").unlink(missing_ok=True)
        outside_dir.rmdir()


def test_save_path_is_resolved_once_not_once_per_file(tmp_path, monkeypatch):
    """Each Path.resolve() opens an NT handle (~1.8 ms on Windows) -- the
    root must be resolved once per call, not once per file."""
    for name in ("a.bin", "b.bin", "c.bin"):
        (tmp_path / name).write_bytes(b"x")
    handle = MagicMock()
    handle.torrent_file.return_value = _mock_torrent_info([("a.bin", 1), ("b.bin", 1), ("c.bin", 1)])
    sm = _session_manager_with_handle("hash1", str(tmp_path), handle)
    resolved = []
    real_resolve = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda self, *a, **k: resolved.append(self) or real_resolve(self, *a, **k))

    assert sm.get_allocated_size("hash1") == 3
    assert resolved.count(tmp_path) == 1
