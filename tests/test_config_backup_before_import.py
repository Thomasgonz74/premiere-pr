"""Tests for the config-backup-before-import safety net (bridge_profile_security.py).

Exercises _backup_current_config() directly -- a plain file-I/O helper, no
QApplication/QWebEngine needed, consistent with how paths.py-dependent
helpers are already tested elsewhere (test_crash_logging.py, test_persistence.py).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from torrent2000.config.paths import get_config_backups_dir, get_config_path
from torrent2000.ui.web.bridge_profile_security import _backup_current_config


def test_no_backup_created_when_no_config_exists_yet(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))

    _backup_current_config()

    assert list(get_config_backups_dir().glob("config-*.json")) == []


def test_backup_snapshots_current_config_content(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    get_config_path().write_text('{"theme": "luna_xp"}', encoding="utf-8")

    _backup_current_config()

    backups = list(get_config_backups_dir().glob("config-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"theme": "luna_xp"}'


def test_only_the_five_most_recent_backups_are_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    get_config_path().write_text("{}", encoding="utf-8")
    backups_dir = get_config_backups_dir()

    # Pre-seed 5 backups with names that sort before any real timestamp
    # generated today, so a 6th real backup should evict the oldest of them.
    for i in range(5):
        (backups_dir / f"config-00000000-00000{i}.json").write_text("{}", encoding="utf-8")

    _backup_current_config()

    assert len(list(backups_dir.glob("config-*.json"))) == 5
    assert not (backups_dir / "config-00000000-000000.json").exists()
