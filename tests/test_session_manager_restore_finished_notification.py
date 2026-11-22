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


def test_a_recheck_of_a_complete_torrent_does_not_refire_finished(qapp, tmp_path):
    """libtorrent fires torrent_finished_alert again once a recheck confirms
    the data: a scheduled recheck re-ran the post-complete unzip, posted the
    webhook and started a shutdown countdown with nobody at the PC."""
    save_path = tmp_path / "downloads"
    save_path.mkdir()
    torrent_path = _make_already_complete_torrent(save_path)
    sm = SessionManager(Settings())
    finished_events = []
    sm.torrent_finished.connect(finished_events.append)
    info_hash = sm.add_torrent_from_file(torrent_path, save_path=str(save_path))
    assert _run_ticks(qapp, sm, lambda: finished_events and sm.get_record(info_hash).progress >= 1.0)

    sm.recheck_torrent(info_hash)
    _run_ticks(qapp, sm, lambda: len(finished_events) > 1, timeout=3.0)

    assert finished_events == [info_hash]
    sm.shutdown()


def test_a_recheck_that_redownloads_bad_pieces_reports_the_finish_and_scans(qapp, tmp_path, monkeypatch):
    """The pieces a recheck finds bad are downloaded again: that finish is
    new data on disk, Defender must scan it. Whole window spent between two
    status samples (no tick), as with a fast peer."""
    from unittest.mock import MagicMock

    from torrent2000.engine import antivirus_scan_service

    save_path = tmp_path / "downloads"
    save_path.mkdir()
    torrent_path = _make_already_complete_torrent(save_path)
    seed_path = tmp_path / "seed"
    seed_path.mkdir()
    (seed_path / "already_complete.bin").write_bytes((save_path / "already_complete.bin").read_bytes())
    seeder = lt.session({"listen_interfaces": "127.0.0.1:0", "enable_dht": False, "enable_lsd": False})
    seeder.add_torrent({"ti": lt.torrent_info(torrent_path), "save_path": str(seed_path)})

    settings = Settings()
    settings.scan_completed_files_with_defender = True
    pool = MagicMock()
    monkeypatch.setattr(antivirus_scan_service, "QThreadPool", pool)
    sm = SessionManager(settings)
    scanner = antivirus_scan_service.AntivirusScanService(sm, settings)  # noqa: F841 (kept alive)
    finished_events = []
    sm.torrent_finished.connect(finished_events.append)
    info_hash = sm.add_torrent_from_file(torrent_path, save_path=str(save_path))
    assert _run_ticks(qapp, sm, lambda: finished_events and sm.get_record(info_hash).progress >= 1.0)
    pool.reset_mock()

    with open(save_path / "already_complete.bin", "r+b") as f:
        f.seek(16 * 1024 + 5)
        f.write(b"XXXX")
    handle = sm._handles[info_hash]
    sm.recheck_torrent(info_hash)
    deadline = time.monotonic() + 10
    while handle.status().state != lt.torrent_status.downloading and time.monotonic() < deadline:
        time.sleep(0.02)
    handle.connect_peer(("127.0.0.1", seeder.listen_port()))
    while not handle.status().is_seeding and time.monotonic() < deadline:
        time.sleep(0.02)
    _run_ticks(qapp, sm, lambda: len(finished_events) > 1, timeout=3.0)

    assert finished_events == [info_hash, info_hash]
    pool.globalInstance.return_value.start.assert_called_once()
    sm.shutdown()


def test_a_recheck_once_its_drive_is_back_reports_no_new_finish(qapp, tmp_path):
    """Restored while its drive was unplugged, a complete torrent checks as
    missing (progress 0); rechecked once the drive is back, its data is whole
    again: nothing was downloaded -- no toast, webhook, post-complete move or
    shutdown countdown."""
    save_path = tmp_path / "drive"
    save_path.mkdir()
    torrent_path = _make_already_complete_torrent(save_path)
    sm1 = SessionManager(Settings())
    info_hash = sm1.add_torrent_from_file(torrent_path, save_path=str(save_path))
    assert _run_ticks(qapp, sm1, lambda: sm1.get_record(info_hash).progress >= 1.0)
    sm1.shutdown()
    unplugged = tmp_path / "unplugged"
    save_path.rename(unplugged)

    sm2 = SessionManager(Settings())
    finished_events = []
    sm2.torrent_finished.connect(finished_events.append)
    try:
        # Bound, and its check found the data missing.
        assert _run_ticks(
            qapp, sm2, lambda: info_hash in sm2._handles and info_hash not in sm2._pending_restore_confirmation
        )
        unplugged.rename(save_path)  # the drive is back
        sm2.recheck_torrent(info_hash)
        assert _run_ticks(qapp, sm2, lambda: sm2.get_record(info_hash).progress >= 1.0)
        _run_ticks(qapp, sm2, lambda: False, timeout=1.0)
    finally:
        sm2.shutdown()

    assert finished_events == []


def test_a_paused_torrent_is_rechecked_at_once_and_left_paused(qapp, tmp_path):
    """libtorrent left a paused torrent's check at 0 % until a resume, which
    CCCP refuses at 0 %; after a restart, that resume fired the whole
    "download finished" chain (toast, webhook, post-complete move...)."""
    from torrent2000.theme_ids import CCCP_THEME_ID

    save_path = tmp_path / "downloads"
    save_path.mkdir()
    torrent_path = _make_already_complete_torrent(save_path)
    settings = Settings()
    sm1 = SessionManager(settings)
    info_hash = sm1.add_torrent_from_file(torrent_path, save_path=str(save_path))
    assert _run_ticks(qapp, sm1, lambda: sm1.get_record(info_hash).progress >= 1.0)
    settings.theme = CCCP_THEME_ID
    handle = sm1._handles[info_hash]

    sm1.pause_torrent(info_hash)
    sm1.recheck_torrent(info_hash)

    checked = _run_ticks(
        qapp, sm1, lambda: handle.status().progress >= 1.0 and sm1.get_record(info_hash).progress >= 1.0
    )
    status = handle.status()
    sm1.shutdown()
    assert checked and status.paused and not status.flags & lt.torrent_flags.auto_managed
    sm2 = SessionManager(settings)
    finished_events, blocked = [], []
    sm2.torrent_finished.connect(finished_events.append)
    sm2.download_blocked_by_theme.connect(blocked.append)
    try:
        assert _run_ticks(qapp, sm2, lambda: info_hash in sm2._handles and sm2.get_record(info_hash).progress >= 1.0)
        sm2.resume_torrent(info_hash)
        _run_ticks(qapp, sm2, lambda: False, timeout=1.5)
    finally:
        sm2.shutdown()

    assert finished_events == [] and blocked == []


def test_a_paused_torrent_resumed_during_its_recheck_is_not_paused_again(qapp, tmp_path):
    save_path = tmp_path / "downloads"
    save_path.mkdir()
    torrent_path = _make_already_complete_torrent(save_path)
    sm = SessionManager(Settings())
    try:
        info_hash = sm.add_torrent_from_file(torrent_path, save_path=str(save_path))
        assert _run_ticks(qapp, sm, lambda: sm.get_record(info_hash).progress >= 1.0)
        handle = sm._handles[info_hash]

        sm.pause_torrent(info_hash)
        sm.recheck_torrent(info_hash)
        sm.resume_torrent(info_hash)

        assert _run_ticks(qapp, sm, lambda: handle.status().progress >= 1.0)
        _run_ticks(qapp, sm, lambda: False, timeout=1.0)
        assert not handle.status().paused
    finally:
        sm.shutdown()


def test_a_torrent_file_is_named_at_the_add_not_at_its_first_status(qapp, tmp_path):
    """atp.name only holds a magnet's dn=: a .torrent finishing before its
    first status tick had an empty name in the "download finished" toast and
    webhook, and Defender scanned the whole download folder for it."""
    save_path = tmp_path / "downloads"
    save_path.mkdir()
    torrent_path = _make_already_complete_torrent(save_path)
    sm = SessionManager(Settings())
    try:
        info_hash = sm.add_torrent_from_file(torrent_path, save_path=str(save_path))

        assert sm.get_record(info_hash).name == "already_complete.bin"
    finally:
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
