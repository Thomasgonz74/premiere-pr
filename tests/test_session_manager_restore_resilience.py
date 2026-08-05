"""A single corrupt/stale .fastresume entry must not crash the whole app at
startup -- _restore_previous_session() previously only guarded
add_params.info_hash_hex(atp), not the session.add_torrent(atp) call that
can actually raise on bad/stale data.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_resume_dir
from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager


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
