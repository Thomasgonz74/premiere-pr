"""A magnet added for analysis (add_torrent_from_magnet, the Add page's
"Analyser" and RSS) with a real local seeder: a paused torrent reaches no
peer, so it must still fetch its metadata -- and download nothing until
start_after_analysis."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import persistence
from torrent2000.engine.session_manager import SessionManager

PIECE = 16 * 1024


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path / "appdata"))


def _wait(qapp, condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.05)
    return condition()


def _session_manager():
    settings = Settings()
    settings.network_interface = "127.0.0.1"
    return SessionManager(settings)


def test_an_analysed_magnet_gets_its_metadata_but_no_data_until_started(tmp_path, qapp):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "alpha.bin").write_bytes(os.urandom(40 * PIECE))
    fs = lt.file_storage()
    lt.add_files(fs, str(seed / "alpha.bin"))
    ct = lt.create_torrent(fs, PIECE, flags=lt.create_torrent.v1_only)
    lt.set_piece_hashes(ct, str(seed))
    seeder = lt.session({"listen_interfaces": "127.0.0.1:0", "enable_dht": False, "enable_lsd": False,
                         "enable_upnp": False, "enable_natpmp": False})
    atp = lt.add_torrent_params()
    atp.ti = lt.torrent_info(lt.bdecode(lt.bencode(ct.generate())))
    atp.save_path = str(seed)
    seeding = seeder.add_torrent(atp)
    assert _wait(qapp, lambda: seeding.status().is_seeding)
    magnet = f"magnet:?xt=urn:btih:{atp.ti.info_hashes().v1}&x.pe=127.0.0.1:{seeder.listen_port()}"

    sm = _session_manager()
    received = []
    sm.metadata_received.connect(received.append)
    try:
        info_hash = sm.add_torrent_from_magnet(magnet, str(tmp_path / "dl"))
        got_metadata = _wait(qapp, lambda: received)
        handle = sm._handles[info_hash]
        flags, status = handle.flags(), handle.status()
        held = (bool(flags & lt.torrent_flags.paused), bool(flags & lt.torrent_flags.upload_mode),
                status.total_payload_download)

        sm.start_after_analysis(info_hash)
        completed = _wait(qapp, lambda: handle.status().is_seeding)
    finally:
        sm.shutdown(timeout_ms=0)

    assert got_metadata
    assert held == (True, False, 0)
    assert completed


def test_a_magnet_saved_while_held_comes_back_paused_not_stuck_in_upload_mode(tmp_path, qapp):
    info_hash = "ab" * 20
    atp = lt.parse_magnet_uri(f"magnet:?xt=urn:btih:{info_hash}")
    atp.save_path = str(tmp_path / "dl")
    # The flags add_torrent_from_magnet gives it until its metadata comes.
    atp.flags &= ~(lt.torrent_flags.auto_managed | lt.torrent_flags.paused)
    atp.flags |= lt.torrent_flags.upload_mode
    persistence.save_resume_params(info_hash, atp)

    sm = _session_manager()
    try:
        assert _wait(qapp, lambda: info_hash in sm._handles)
        flags = sm._handles[info_hash].flags()
    finally:
        sm.shutdown(timeout_ms=0)

    assert (bool(flags & lt.torrent_flags.paused), bool(flags & lt.torrent_flags.upload_mode)) == (True, False)
