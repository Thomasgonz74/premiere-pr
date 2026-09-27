"""Tests for SessionManager.set_sequential_download's streaming
reinforcement: beyond handle.set_sequential_download(), it also applies
deadline-based piece priorities (handle.set_piece_deadline) to the head of
the torrent's largest file (see engine/session_manager.py's
_apply_streaming_deadlines). Mocking pattern mirrors
test_session_manager_allocated_size.py (bypass __init__, fake torrent_info).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

from torrent2000.engine.session_manager import (
    _STREAMING_DEADLINE_STEP_MS,
    _STREAMING_HEAD_PIECE_COUNT,
    SessionManager,
)


def _mock_torrent_info(file_sizes: list[int], piece_length: int, num_pieces: int) -> MagicMock:
    fs = MagicMock()
    fs.num_files.return_value = len(file_sizes)
    fs.file_size.side_effect = lambda i: file_sizes[i]
    offsets = []
    running = 0
    for size in file_sizes:
        offsets.append(running)
        running += size
    fs.file_offset.side_effect = lambda i: offsets[i]
    ti = MagicMock()
    ti.files.return_value = fs
    ti.piece_length.return_value = piece_length
    ti.num_pieces.return_value = num_pieces
    return ti


def _session_manager_with_handle(info_hash: str, handle) -> SessionManager:
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    sm._handles = {info_hash: handle}
    return sm


def test_enabling_sets_sequential_flag_and_applies_head_piece_deadlines():
    handle = MagicMock()
    # A small file (50 bytes) followed by the largest file (10000 bytes),
    # piece_length=100 -- the largest file spans pieces 0..100, but the head
    # window (_STREAMING_HEAD_PIECE_COUNT=30) caps it at pieces 0..29.
    handle.torrent_file.return_value = _mock_torrent_info([50, 10000], piece_length=100, num_pieces=105)
    sm = _session_manager_with_handle("hash1", handle)

    sm.set_sequential_download("hash1", True)

    handle.set_sequential_download.assert_called_once_with(True)
    assert handle.set_piece_deadline.call_count == _STREAMING_HEAD_PIECE_COUNT
    first_call = handle.set_piece_deadline.call_args_list[0]
    last_call = handle.set_piece_deadline.call_args_list[-1]
    assert first_call.args == (0, 0)
    assert last_call.args == (_STREAMING_HEAD_PIECE_COUNT - 1, (_STREAMING_HEAD_PIECE_COUNT - 1) * _STREAMING_DEADLINE_STEP_MS)


def test_head_window_never_exceeds_the_largest_files_actual_piece_range():
    handle = MagicMock()
    # Largest file only spans 5 pieces total -- must not request deadlines
    # for pieces beyond it even though the head window would allow more.
    handle.torrent_file.return_value = _mock_torrent_info([0, 500], piece_length=100, num_pieces=5)
    sm = _session_manager_with_handle("hash1", handle)

    sm.set_sequential_download("hash1", True)

    assert handle.set_piece_deadline.call_count == 5
    called_pieces = [call.args[0] for call in handle.set_piece_deadline.call_args_list]
    assert called_pieces == [0, 1, 2, 3, 4]


def test_disabling_clears_piece_deadlines_instead_of_setting_them():
    handle = MagicMock()
    sm = _session_manager_with_handle("hash1", handle)

    sm.set_sequential_download("hash1", False)

    handle.set_sequential_download.assert_called_once_with(False)
    handle.clear_piece_deadlines.assert_called_once()
    handle.set_piece_deadline.assert_not_called()


def test_metadata_not_yet_available_sets_the_flag_without_raising():
    handle = MagicMock()
    handle.torrent_file.return_value = None  # magnet still resolving
    sm = _session_manager_with_handle("hash1", handle)

    sm.set_sequential_download("hash1", True)  # must not raise

    handle.set_sequential_download.assert_called_once_with(True)
    handle.set_piece_deadline.assert_not_called()


def test_unknown_info_hash_is_a_noop():
    sm = _session_manager_with_handle("hash1", MagicMock())

    sm.set_sequential_download("unknown", True)  # must not raise
