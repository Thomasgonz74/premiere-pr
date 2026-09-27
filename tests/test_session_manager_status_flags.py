"""_on_tick's post_torrent_updates() passes explicit status flags: name and
save_path must still be filled (raw 64/128 literals, not exposed by the
2.0.13 bindings), while the per-piece bitfields libtorrent computes by
default -- never read by status_to_record -- are no longer requested.
"""

import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine import session_manager as session_manager_module
from torrent2000.engine.session_manager import SessionManager


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path / "appdata"))


def test_status_updates_fill_name_and_save_path_without_piece_bitfields(qapp, tmp_path):
    content = tmp_path / "flags_probe.bin"
    content.write_bytes(os.urandom(64 * 1024))
    fs = lt.file_storage()
    lt.add_files(fs, str(content))
    ct = lt.create_torrent(fs, piece_size=16 * 1024)
    lt.set_piece_hashes(ct, str(tmp_path))
    torrent_path = tmp_path / "flags_probe.torrent"
    torrent_path.write_bytes(lt.bencode(ct.generate()))

    seen = []
    real_status_to_record = session_manager_module.status_to_record

    def spy(status, record):
        seen.append((status.name, status.save_path, len(status.pieces)))
        real_status_to_record(status, record)

    sm = SessionManager(Settings())
    try:
        sm.add_torrent_from_file(str(torrent_path), save_path=str(tmp_path))
        with patch.object(session_manager_module, "status_to_record", spy):
            deadline = time.monotonic() + 10.0
            while not seen and time.monotonic() < deadline:
                qapp.processEvents()
                sm._on_tick()
                time.sleep(0.05)
    finally:
        sm.shutdown(timeout_ms=0)

    assert seen, "no state_update_alert within 10 s"
    assert seen[0] == ("flags_probe.bin", str(tmp_path), 0)
