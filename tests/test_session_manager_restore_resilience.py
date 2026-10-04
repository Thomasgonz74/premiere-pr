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
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_resume_dir
from torrent2000.config.settings import Settings
from torrent2000.engine import session_manager as session_manager_module
from torrent2000.engine.persistence import save_resume_params
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.tag_service import TagService
from torrent2000.engine.torrent_item import TorrentRecord
from torrent2000.ui.web.bridge_downloads import DownloadsBridge

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


def _restoring(*info_hashes) -> SessionManager:
    """A SessionManager (real signals, no libtorrent session) still waiting
    for the add_torrent_alerts of these restored, complete torrents."""
    sm = SessionManager.__new__(SessionManager)
    QObject.__init__(sm)
    sm._pending_restore = set(info_hashes)
    sm._pending_restore_confirmation = set(info_hashes)
    sm._records = {ih: TorrentRecord(info_hash=ih) for ih in info_hashes}
    sm._handles = {}
    return sm


def _restore_settings() -> Settings:
    settings = Settings()
    settings.network_interface = "127.0.0.1"
    return settings


def test_rejected_restore_drops_its_record_but_other_add_errors_do_not():
    sm = _restoring("restored")
    sm._records["manual"] = TorrentRecord(info_hash="manual")
    failed, removed = [], []
    sm.torrent_restore_failed.connect(failed.append)
    sm.torrent_removed.connect(removed.append)

    sm._on_torrent_added("restored", MagicMock(), "invalid resume data")
    sm._on_torrent_added("manual", MagicMock(), "some error")  # an add_torrent_from_* add: not ours to undo

    assert "restored" not in sm._records
    assert sm._pending_restore == set() and sm._pending_restore_confirmation == set()
    assert failed == ["restored"] and removed == []
    assert "manual" in sm._records
    assert sm._handles == {}


def test_a_rejected_restore_takes_its_row_away_but_keeps_its_tags_and_share_limit():
    """Its .fastresume stays for next launch, so must everything keyed on it
    (TagService.drop_orphans keeps those tags on purpose)."""
    sm = _restoring("restored")
    tags = TagService()
    tags.add("restored", "linux")
    share_limits = ShareLimitService(sm, Settings())
    share_limits.track("restored", time_limit_seconds=3600, data_limit_bytes=None)
    bridge = DownloadsBridge(sm, MagicMock(), tag_service=tags)
    rows_removed = []
    bridge.recordRemoved.connect(rows_removed.append)

    sm._on_torrent_added("restored", MagicMock(), "invalid resume data")

    assert rows_removed == ["restored"]
    assert TagService().get("restored") == ["linux"]
    assert share_limits.is_tracked("restored")


def test_a_rejected_restore_leaves_the_same_torrent_added_again_by_hand_alone():
    sm = _restoring("ih")
    manual_record = sm._records["ih"] = TorrentRecord(info_hash="ih")  # add_torrent_from_file() before the alert
    live_handle = sm._handles["ih"] = MagicMock()
    failed = []
    sm.torrent_restore_failed.connect(failed.append)

    sm._on_torrent_added("ih", MagicMock(), "invalid resume data")

    assert sm.get_record("ih") is manual_record and sm._handles["ih"] is live_handle
    assert failed == []
    assert sm._pending_restore_confirmation == set()  # its first finish will be a real one


def test_restored_handles_are_bound_on_the_first_event_loop_pass_not_the_first_tick(qapp, tmp_path):
    atp = lt.parse_magnet_uri(f"magnet:?xt=urn:btih:{_INFO_HASH}&dn=test")
    atp.save_path = str(tmp_path)
    save_resume_params(_INFO_HASH, atp)

    session_manager = SessionManager(_restore_settings())
    try:
        session_manager._timer.setInterval(60_000)  # no tick during this test
        session_manager._session.get_torrents()  # returns once libtorrent has handled the add

        deadline = time.monotonic() + 5
        while _INFO_HASH not in session_manager._handles and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        assert session_manager._handles[_INFO_HASH].is_valid()
    finally:
        session_manager.shutdown(timeout_ms=0)


def test_a_restore_larger_than_the_alert_queue_still_binds_every_handle(qapp, tmp_path, monkeypatch):
    """Before the event loop runs nothing pops libtorrent's alert queue, and
    past alert_queue_size it drops alerts, add_torrent_alerts included. The
    default 2000 only overflows past ~3,600 restores: shrunk to 20 here, 200
    overflow it the same way."""
    real_settings = session_manager_module._build_session_settings
    monkeypatch.setattr(
        session_manager_module, "_build_session_settings", lambda s: {**real_settings(s), "alert_queue_size": 20}
    )
    for i in range(200):
        info_hash = f"{i + 1:040x}"
        atp = lt.parse_magnet_uri(f"magnet:?xt=urn:btih:{info_hash}")
        atp.save_path = str(tmp_path)
        save_resume_params(info_hash, atp)

    session_manager = SessionManager(_restore_settings())
    try:
        session_manager._session.get_torrents()  # every add handled, all their alerts still queued
        session_manager._dispatch_alerts()

        assert len(session_manager._handles) == 200
        assert session_manager._pending_restore == set()
    finally:
        session_manager.shutdown(timeout_ms=0)
