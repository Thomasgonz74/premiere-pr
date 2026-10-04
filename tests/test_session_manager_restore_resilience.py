"""A single corrupt/stale .fastresume entry must not crash the whole app at
startup -- _restore_previous_session() previously only guarded
add_params.info_hash_hex(atp), not the session.add_torrent(atp) call that
can actually raise on bad/stale data.

Restoration now goes through async_add_torrent: records exist as soon as
SessionManager is built, and each handle is bound (or the record dropped, if
libtorrent rejects the entry) when its add_torrent_alert arrives.
"""

import os
import time
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_resume_dir
from torrent2000.config.settings import Settings
from torrent2000.engine.persistence import save_resume_params
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord

_INFO_HASH = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def test_corrupt_resume_file_does_not_crash_startup():
    (get_resume_dir() / "garbage.fastresume").write_bytes(b"d8:announce4:junke")

    settings = Settings()
    session_manager = SessionManager(settings)  # must not raise

    assert session_manager.all_records() == []


def test_restored_torrent_gets_its_handle_from_the_add_alert(qapp, tmp_path):
    atp = lt.parse_magnet_uri(f"magnet:?xt=urn:btih:{_INFO_HASH}&dn=test")
    atp.save_path = str(tmp_path)
    save_resume_params(_INFO_HASH, atp)

    session_manager = SessionManager(Settings())
    try:
        # The record exists right away; the handle only once the tick loop
        # has dispatched the add_torrent_alert -- the constructor itself never
        # waits on libtorrent's network thread.
        assert session_manager.get_record(_INFO_HASH) is not None
        assert _INFO_HASH not in session_manager._handles

        deadline = time.monotonic() + 10
        while _INFO_HASH not in session_manager._handles and time.monotonic() < deadline:
            qapp.processEvents()
            session_manager._on_tick()
            time.sleep(0.05)

        assert session_manager._handles[_INFO_HASH].is_valid()
    finally:
        session_manager.shutdown(timeout_ms=0)


def test_rejected_restore_drops_its_record_but_other_add_errors_do_not():
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    sm._pending_restore = {"restored"}
    sm._pending_restore_confirmation = {"restored"}
    sm._records = {"restored": TorrentRecord(info_hash="restored"), "manual": TorrentRecord(info_hash="manual")}
    sm._handles = {}
    sm.torrent_removed = MagicMock()

    sm._on_torrent_added("restored", MagicMock(), "invalid resume data")
    sm._on_torrent_added("manual", MagicMock(), "some error")  # an add_torrent_from_* add: not ours to undo

    assert "restored" not in sm._records
    assert sm._pending_restore == set() and sm._pending_restore_confirmation == set()
    sm.torrent_removed.emit.assert_called_once_with("restored")
    assert "manual" in sm._records
    assert sm._handles == {}
