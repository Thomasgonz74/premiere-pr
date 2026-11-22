"""A magnet is held for analysis without being paused: a paused torrent
contacts no peer, so its metadata never arrived and the Add page, RSS,
search and clipboard paths all waited for it forever. It runs in upload
mode instead -- metadata, but no piece, until start_after_analysis -- and
comes back the same way after a restart."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_awaiting_analysis_path, get_magnets_to_start_path
from torrent2000.config.settings import Settings
from torrent2000.engine import add_params, persistence
from torrent2000.engine.session_manager import SessionManager
from torrent2000.theme_ids import CCCP_THEME_ID

_MAGNET = "magnet:?xt=urn:btih:" + "ab" * 20 + "&dn=pending"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path / "appdata"))


def _loopback_settings() -> Settings:
    settings = Settings()
    settings.network_interface = "127.0.0.1"
    settings.restrict_discovery = True
    return settings


def _pump(app, session_manager, predicate, timeout=15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        session_manager._on_tick()
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _seeder(tmp_path, names=("payload.bin",)):
    """A plain libtorrent session on 127.0.0.1 seeding 64 KiB per file, and a
    magnet pointing straight at it (x.pe), so no tracker or DHT is involved."""
    data_dir = tmp_path / "seed"
    (data_dir / "pack").mkdir(parents=True)
    for name in names:
        (data_dir / "pack" / name).write_bytes(os.urandom(64 * 1024))
    fs = lt.file_storage()
    lt.add_files(fs, str(data_dir / "pack"))
    ct = lt.create_torrent(fs, piece_size=16 * 1024)
    lt.set_piece_hashes(ct, str(data_dir))
    ti = lt.torrent_info(ct.generate())
    session = lt.session(
        {
            "listen_interfaces": "127.0.0.1:0",
            "enable_dht": False,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
        }
    )
    atp = lt.add_torrent_params()
    atp.ti = ti
    atp.save_path = str(data_dir)
    handle = session.add_torrent(atp)
    deadline = time.monotonic() + 10
    while not handle.status().is_seeding and time.monotonic() < deadline:
        time.sleep(0.05)
    return session, f"{lt.make_magnet_uri(ti)}&x.pe=127.0.0.1:{session.listen_port()}"


def test_a_magnet_fetches_its_metadata_but_no_piece_until_started(qapp, tmp_path):
    seeder, magnet = _seeder(tmp_path)
    sm = SessionManager(_loopback_settings())
    sm._session.apply_settings({"listen_interfaces": "127.0.0.1:0"})  # never clash on 6881
    received = []
    sm.metadata_received.connect(received.append)
    try:
        info_hash = sm.add_torrent_from_magnet(magnet, str(tmp_path / "leech"))

        assert _pump(qapp, sm, lambda: received == [info_hash]), "metadata never arrived"
        _pump(qapp, sm, lambda: False, timeout=1.0)  # time enough to download 64 KiB from loopback
        assert sm._handles[info_hash].status().total_done == 0
        assert sm.get_record(info_hash).awaiting_analysis

        sm.start_after_analysis(info_hash)

        assert _pump(qapp, sm, lambda: sm.get_record(info_hash).progress >= 1.0)
    finally:
        sm.shutdown(timeout_ms=0)
        del seeder


def test_a_magnet_awaiting_analysis_comes_back_awaiting_after_a_restart(qapp, tmp_path):
    sm1 = SessionManager(_loopback_settings())
    info_hash = sm1.add_torrent_from_magnet(_MAGNET, str(tmp_path))
    sm1.shutdown()

    sm2 = SessionManager(_loopback_settings())
    try:
        assert sm2.get_record(info_hash).awaiting_analysis
        assert _pump(qapp, sm2, lambda: info_hash in sm2._handles)
        sm2.pause_torrent(info_hash)
        sm2.resume_torrent(info_hash)  # back to fetching metadata, not downloading
        status = sm2._handles[info_hash].status()
        assert status.upload_mode and not status.paused and not status.auto_managed

        sm2.start_after_analysis(info_hash)
        status = sm2._handles[info_hash].status()
        assert not status.upload_mode and status.auto_managed
    finally:
        sm2.shutdown()

    sm3 = SessionManager(_loopback_settings())
    try:
        assert not sm3.get_record(info_hash).awaiting_analysis
    finally:
        sm3.shutdown(timeout_ms=0)


def test_starting_a_magnet_nobody_analyses_any_more_scans_it_first(qapp, tmp_path):
    """Left awaiting by a restart or by another magnet analysed on the Add
    page: the Downloads page's start does what RSS does once the metadata is in."""
    seeder, magnet = _seeder(tmp_path, names=("film.mp4", "film.mp4.exe"))
    sm = SessionManager(_loopback_settings())
    sm._session.apply_settings({"listen_interfaces": "127.0.0.1:0"})
    try:
        bare_magnet, _, peer = magnet.partition("&x.pe=")  # no peer until asked: no metadata yet
        info_hash = sm.add_torrent_from_magnet(bare_magnet, str(tmp_path / "leech"))
        sm.start_awaiting_magnet(info_hash)
        assert persistence.load_json(get_magnets_to_start_path(), []) == [info_hash]
        host, _, port = peer.partition(":")
        sm._handles[info_hash].connect_peer((host, int(port)))

        assert _pump(qapp, sm, lambda: sm.get_record(info_hash).progress >= 1.0)
        priorities = dict(zip((f.path for f in sm.get_torrent_files(info_hash)), sm.get_file_priorities(info_hash)))
        assert priorities[os.path.join("pack", "film.mp4.exe")] == 0
        assert priorities[os.path.join("pack", "film.mp4")] > 0
        assert persistence.load_json(get_magnets_to_start_path(), []) == []
    finally:
        sm.shutdown(timeout_ms=0)
        del seeder


def test_a_magnet_started_before_its_metadata_still_waits_for_it_after_a_restart(qapp, tmp_path):
    sm1 = SessionManager(_loopback_settings())
    info_hash = sm1.add_torrent_from_magnet(_MAGNET, str(tmp_path))
    sm1.start_awaiting_magnet(info_hash)
    sm1.shutdown()

    sm2 = SessionManager(_loopback_settings())
    try:
        assert info_hash in sm2._start_once_analysed
    finally:
        sm2.shutdown(timeout_ms=0)


def test_after_an_abnormal_exit_the_awaiting_set_wins_over_the_resume_data(qapp, tmp_path):
    """awaiting_analysis.json is written at once, the .fastresume only every
    so often: each can be the older one after a crash."""
    sm1 = SessionManager(_loopback_settings())
    saved_held = sm1.add_torrent_from_magnet(_MAGNET, str(tmp_path))
    saved_started = sm1.add_torrent_from_magnet("magnet:?xt=urn:btih:" + "cd" * 20, str(tmp_path))
    sm1.start_after_analysis(saved_started)
    sm1.shutdown()
    # The awaiting set says the opposite of each one's resume data.
    persistence.save_json(get_awaiting_analysis_path(), [saved_started])

    sm2 = SessionManager(_loopback_settings())
    try:
        assert _pump(qapp, sm2, lambda: saved_held in sm2._handles and saved_started in sm2._handles)
        started_now, held_now = sm2._handles[saved_held].status(), sm2._handles[saved_started].status()
        assert not started_now.upload_mode and started_now.auto_managed
        assert held_now.upload_mode and not held_now.paused and not held_now.auto_managed
    finally:
        sm2.shutdown(timeout_ms=0)


def test_starting_a_held_magnet_under_cccp_is_refused_not_queued(qapp, tmp_path):
    settings = _loopback_settings()
    settings.theme = CCCP_THEME_ID
    sm = SessionManager(settings)
    blocked = []
    sm.download_blocked_by_theme.connect(blocked.append)
    try:
        info_hash = sm.add_torrent_from_magnet(_MAGNET, str(tmp_path))

        assert sm.start_awaiting_magnet(info_hash) is False  # the page shows no "will start" banner
        assert blocked == [info_hash]
        assert info_hash not in sm._start_once_analysed
    finally:
        sm.shutdown(timeout_ms=0)


def test_under_cccp_a_magnet_started_before_its_check_is_judged_on_the_check(qapp, tmp_path):
    """The Share page starts its magnet at once: refused on the record's 0 %,
    "Nyet." next to "Sharing started." and the share left awaiting analysis at
    100 %. Complete data is a share; missing data is refused, once checked."""
    import shutil

    shared_seeder, shared_magnet = _seeder(tmp_path / "shared")
    new_seeder, new_magnet = _seeder(tmp_path / "new")
    shutil.copytree(tmp_path / "shared" / "seed", tmp_path / "mine")
    settings = _loopback_settings()
    settings.theme = CCCP_THEME_ID
    sm = SessionManager(settings)
    sm._session.apply_settings({"listen_interfaces": "127.0.0.1:0"})  # never clash on 6881
    blocked = []
    sm.download_blocked_by_theme.connect(blocked.append)
    try:
        shared = sm.add_torrent_from_magnet(shared_magnet, str(tmp_path / "mine"))
        sm.start_after_analysis(shared)
        new = sm.add_torrent_from_magnet(new_magnet, str(tmp_path / "leech"))
        sm.start_after_analysis(new)

        handle = sm._handles[shared]
        assert _pump(qapp, sm, lambda: blocked and handle.status().is_seeding and not handle.status().upload_mode)
        _pump(qapp, sm, lambda: False, timeout=1.0)
        assert blocked == [new]
        assert not sm.get_record(shared).awaiting_analysis and handle.status().auto_managed
        assert sm.get_record(new).awaiting_analysis and sm._handles[new].status().total_done == 0
    finally:
        sm.shutdown(timeout_ms=0)
        del shared_seeder, new_seeder


def test_a_torrent_file_added_after_its_magnet_was_lost_in_a_crash_is_not_held(qapp, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "f.bin").write_bytes(os.urandom(64 * 1024))
    fs = lt.file_storage()
    lt.add_files(fs, str(tmp_path / "data" / "f.bin"))
    ct = lt.create_torrent(fs, piece_size=16 * 1024)
    lt.set_piece_hashes(ct, str(tmp_path / "data"))
    torrent_path = tmp_path / "t.torrent"
    torrent_path.write_bytes(lt.bencode(ct.generate()))
    # Its magnet was added, then the app crashed before any resume save.
    info_hash = str(lt.torrent_info(str(torrent_path)).info_hashes().v1)
    persistence.save_json(get_awaiting_analysis_path(), [info_hash])

    sm = SessionManager(_loopback_settings())
    try:
        assert sm.add_torrent_from_file(str(torrent_path), str(tmp_path / "dl")) == info_hash
        # Else the next restore holds it in upload mode, its download stopped.
        assert persistence.load_json(get_awaiting_analysis_path(), []) == []
    finally:
        sm.shutdown(timeout_ms=0)


def test_a_magnet_paused_while_held_then_started_is_saved_started_at_once(qapp, tmp_path):
    """Not at the next periodic save: a crash meanwhile would bring it back
    paused, the start lost."""
    sm = SessionManager(_loopback_settings())
    try:
        info_hash = sm.add_torrent_from_magnet(_MAGNET, str(tmp_path))
        sm.pause_torrent(info_hash)
        sm.start_after_analysis(info_hash)

        def saved_started():
            saved = [atp for atp in persistence.load_all_resume_params() if add_params.info_hash_hex(atp) == info_hash]
            return bool(saved) and not saved[0].flags & (lt.torrent_flags.paused | lt.torrent_flags.upload_mode)

        assert _pump(qapp, sm, saved_started, timeout=5.0)
    finally:
        sm.shutdown(timeout_ms=0)
