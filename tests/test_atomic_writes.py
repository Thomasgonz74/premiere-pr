"""Regression tests for atomic (temp-file + os.replace) persistence writes.

Covers the three state-writing call sites that must never leave a
truncated/corrupt file behind if the process dies mid-write: Settings.save(),
ShareLimitService._save(), and persistence.save_resume_params(). For each,
we check both that a normal save produces correct content *and* that no
leftover ".tmp" file remains afterward (proof os.replace() actually ran).
"""

import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import libtorrent as lt
import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_config_path, get_resume_dir, get_share_limits_path
from torrent2000.config.settings import Settings
from torrent2000.engine.persistence import (
    load_all_resume_params,
    resume_file_path,
    save_resume_params,
)
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.torrent_item import TorrentRecord

_MAGNET = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=test"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _no_tmp_files_in(directory) -> bool:
    return list(directory.glob("*.tmp")) == []


def test_settings_save_is_atomic(tmp_path):
    settings = Settings.load()
    settings.language = "ja"
    settings.save()

    config_path = get_config_path()
    assert json.loads(config_path.read_text(encoding="utf-8"))["language"] == "ja"
    assert _no_tmp_files_in(config_path.parent)


def test_share_limits_save_is_atomic(tmp_path):
    sm = MagicMock()
    sm.get_record.return_value = TorrentRecord(
        info_hash="abc123", name="x", save_path="C:\\x", all_time_uploaded=500
    )
    service = ShareLimitService(sm, Settings())
    service.track("abc123", time_limit_seconds=3600, data_limit_bytes=None)
    # track() now debounces the actual write (see engine/share_limits.py) --
    # force it through immediately so this test still observes the atomic
    # write it's actually testing, rather than racing a 500ms timer.
    service.flush_pending_save()

    limits_path = get_share_limits_path()
    saved = json.loads(limits_path.read_text(encoding="utf-8"))
    assert saved["abc123"]["time_limit_seconds"] == 3600
    assert saved["abc123"]["uploaded_baseline"] == 500
    assert _no_tmp_files_in(limits_path.parent)


def test_save_resume_params_is_atomic(tmp_path):
    atp = lt.parse_magnet_uri(_MAGNET)
    atp.save_path = "C:/downloads"
    info_hash = "0123456789abcdef0123456789abcdef01234567"

    save_resume_params(info_hash, atp)

    path = resume_file_path(info_hash)
    assert path.exists()
    reloaded = load_all_resume_params()
    assert len(reloaded) == 1
    assert reloaded[0].save_path == "C:/downloads"
    assert _no_tmp_files_in(get_resume_dir())
