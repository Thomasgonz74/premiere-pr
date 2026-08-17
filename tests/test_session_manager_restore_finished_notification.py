"""Regression coverage for: restoring a torrent that was already 100%
complete before this process started must not re-fire torrent_finished on
every relaunch. libtorrent re-emits torrent_finished_alert while verifying a
restored torrent's fast-resume data is still fully present on disk, even
though nothing was (re)downloaded this session -- see
SessionManager._pending_restore_confirmation / _on_torrent_finished and
add_params.resume_data_is_complete.
"""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import add_params
from torrent2000.engine.session_manager import SessionManager


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path / "appdata"))


def _make_already_complete_torrent(save_path) -> str:
    """Writes real file bytes to disk and builds a matching .torrent for
    them, so adding it makes libtorrent see a torrent that's 100% present
    from the very first check -- no download or network needed."""
    content_path = save_path / "already_complete.bin"
    content_path.write_bytes(os.urandom(48 * 1024))

    fs = lt.file_storage()
    lt.add_files(fs, str(content_path))
    ct = lt.create_torrent(fs, piece_size=16 * 1024)
    lt.set_piece_hashes(ct, str(save_path))
    torrent_path = save_path / "already_complete.torrent"
    torrent_path.write_bytes(lt.bencode(ct.generate()))
    return str(torrent_path)


def _run_ticks(app, session_manager, predicate, timeout=10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        session_manager._on_tick()
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_restoring_an_already_complete_torrent_does_not_refire_finished(qapp, tmp_path):
    save_path = tmp_path / "downloads"
    save_path.mkdir()
    torrent_path = _make_already_complete_torrent(save_path)

    # Session 1: add the already-complete torrent and let it settle, then
    # shut down cleanly (saves fast-resume data, as closeEvent does).
    sm1 = SessionManager(Settings())
    info_hash = sm1.add_torrent_from_file(torrent_path, save_path=str(save_path))
    assert _run_ticks(qapp, sm1, lambda: sm1.get_record(info_hash).progress >= 1.0)
    sm1.shutdown()

    # Sessions 2 and 3: relaunch, restoring the same already-complete
    # torrent from resume data each time -- must not notify either time.
    for _ in range(2):
        sm = SessionManager(Settings())
        finished_events = []
        sm.torrent_finished.connect(finished_events.append)
        _run_ticks(qapp, sm, lambda: False, timeout=1.5)  # pump a few ticks
        assert finished_events == []
        sm.shutdown()


def test_genuine_completion_during_the_session_still_notifies(qapp, tmp_path):
    """A torrent restored while genuinely incomplete, then completed by real
    activity this session, must still fire torrent_finished -- the fix must
    not suppress real completions, only the fast-resume reconfirmation."""
    save_path = tmp_path / "downloads"
    save_path.mkdir()
    content_path = save_path / "data.bin"
    content_path.write_bytes(os.urandom(48 * 1024))
    fs = lt.file_storage()
    lt.add_files(fs, str(content_path))
    ct = lt.create_torrent(fs, piece_size=16 * 1024)
    lt.set_piece_hashes(ct, str(save_path))
    torrent_path = save_path / "data.torrent"
    torrent_path.write_bytes(lt.bencode(ct.generate()))

    sm = SessionManager(Settings())
    info_hash = sm.add_torrent_from_file(str(torrent_path), save_path=str(save_path))
    finished_events = []
    sm.torrent_finished.connect(finished_events.append)

    # Directly invoke the callback SessionManager wires to AlertDispatcher,
    # simulating libtorrent firing torrent_finished_alert for a torrent that
    # was never marked as "already complete at restore" (fresh adds never
    # enter _pending_restore_confirmation) -- must be forwarded as real news.
    sm._on_torrent_finished(info_hash)

    assert finished_events == [info_hash]
    sm.shutdown()


# ------------------------------------------------------- resume_data_is_complete


class _FakeAtp:
    def __init__(self, have_pieces, piece_priorities=()):
        self.have_pieces = have_pieces
        self.piece_priorities = list(piece_priorities)


def test_resume_data_is_complete_true_when_all_pieces_present():
    assert add_params.resume_data_is_complete(_FakeAtp([True, True, True])) is True


def test_resume_data_is_complete_false_when_a_wanted_piece_is_missing():
    assert add_params.resume_data_is_complete(_FakeAtp([True, False, True])) is False


def test_resume_data_is_complete_true_when_missing_piece_belongs_to_excluded_file():
    # Priority 0 == excluded file -- never going to be downloaded, so it
    # doesn't count against completeness.
    assert add_params.resume_data_is_complete(_FakeAtp([True, False, True], piece_priorities=[4, 0, 4])) is True


def test_resume_data_is_complete_false_for_empty_have_pieces():
    # No resume data / metadata not yet known -- can't claim completeness.
    assert add_params.resume_data_is_complete(_FakeAtp([])) is False
