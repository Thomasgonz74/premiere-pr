"""Coverage for SessionManager._on_file_error: the file_error_alert branch
must pause the torrent (via pause_torrent, not a raw handle.pause() -- see
pause_torrent's own docstring on why) and always emit the file_error signal,
even for a ghost/invalid handle."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

from torrent2000.engine.session_manager import SessionManager


def _session_manager_with_mock_handles(**handles):
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    sm._handles = dict(handles)
    sm._records = {}
    sm.file_error = MagicMock()
    return sm


def test_on_file_error_pauses_the_torrent_and_emits_the_signal():
    handle = MagicMock()
    sm = _session_manager_with_mock_handles(hash0=handle)

    sm._on_file_error("hash0", "the device is not ready")

    handle.unset_flags.assert_called_once()
    handle.pause.assert_called_once()
    sm.file_error.emit.assert_called_once_with("hash0", "the device is not ready")


def test_on_file_error_with_ghost_handle_still_emits_the_signal():
    handle = MagicMock()
    handle.is_valid.return_value = False
    sm = _session_manager_with_mock_handles(hash0=handle)

    sm._on_file_error("hash0", "boom")  # must not raise

    handle.pause.assert_not_called()
    sm.file_error.emit.assert_called_once_with("hash0", "boom")


def test_on_file_error_unknown_hash_still_emits_the_signal():
    sm = _session_manager_with_mock_handles()

    sm._on_file_error("unknown", "boom")  # must not raise

    sm.file_error.emit.assert_called_once_with("unknown", "boom")
