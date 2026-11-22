"""FilePriorityBridge.getFiles reports each file's current priority, so the
"Modifier les fichiers" dialog starts with an excluded file unchecked (and
saving it untouched keeps it excluded) -- real SessionManager, on a hybrid
torrent whose pad files shift the libtorrent file indices."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_files import files_from_torrent_path
from torrent2000.ui.web.bridge_file_priority import FilePriorityBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path / "appdata"))


def test_get_files_reports_an_excluded_file_as_excluded(tmp_path):
    content = tmp_path / "pack"
    content.mkdir()
    for name in ("film.mkv", "film.mkv.exe", "readme.txt"):
        (content / name).write_bytes(os.urandom(20 * 1024))
    fs = lt.file_storage()
    lt.add_files(fs, str(content))
    ct = lt.create_torrent(fs, piece_size=16 * 1024)  # hybrid: pad files between
    lt.set_piece_hashes(ct, str(tmp_path))
    torrent_path = tmp_path / "pack.torrent"
    torrent_path.write_bytes(lt.bencode(ct.generate()))
    exe_index = next(e.index for e in files_from_torrent_path(str(torrent_path)) if e.path.endswith(".exe"))

    settings = Settings()
    settings.network_interface = "127.0.0.1"
    sm = SessionManager(settings)
    try:
        info_hash = sm.add_torrent_from_file(str(torrent_path), str(tmp_path / "dl"), {exe_index})
        files = FilePriorityBridge(sm).getFiles(info_hash)
    finally:
        sm.shutdown(timeout_ms=0)

    assert {os.path.basename(f["path"]): f["priority"] for f in files} == {
        "film.mkv": 4,
        "film.mkv.exe": 0,
        "readme.txt": 4,
    }
