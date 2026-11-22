"""Tests for the config-backup-before-import safety net (bridge_profile_security.py).

Exercises _backup_current_config() directly -- a plain file-I/O helper, no
QApplication/QWebEngine needed, consistent with how paths.py-dependent
helpers are already tested elsewhere (test_crash_logging.py, test_persistence.py).
"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from torrent2000.config.paths import get_config_backups_dir, get_config_path
from torrent2000.config.redaction import redact_settings_dict
from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.config.settings_history import read_settings_history
from torrent2000.ui.web.bridge_profile_security import ProfileSecurityBridge, _backup_current_config


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
    # Re-serialized (redacted) rather than a byte-for-byte copy -- see
    # redact_settings_dict() -- so compare parsed content, not raw text.
    assert json.loads(backups[0].read_text(encoding="utf-8")) == {"theme": "luna_xp"}


def test_backup_redacts_proxy_password_and_remote_access_token(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    get_config_path().write_text(
        json.dumps({"proxy": {"password": "hunter2"}, "remote_access_token": "s3cret"}), encoding="utf-8"
    )

    _backup_current_config()

    backups = list(get_config_backups_dir().glob("config-*.json"))
    data = json.loads(backups[0].read_text(encoding="utf-8"))
    assert data["proxy"]["password"] == ""
    assert data["remote_access_token"] == ""


def test_backup_redacts_webhook_url_and_rss_passkeys_and_history_skips_webhook(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    settings = Settings.load()
    settings.webhook_url = "https://discord.com/api/webhooks/123/SECRET-TOKEN"
    settings.rss_feeds = [RssFeedSubscription(url="https://t.invalid/rss?passkey=SECRET")]
    settings.save()

    _backup_current_config()

    data = json.loads(next(get_config_backups_dir().glob("config-*.json")).read_text(encoding="utf-8"))
    assert data["webhook_url"] == ""
    assert data["rss_feeds"][0]["url"] == "https://t.invalid/rss?passkey="
    assert "webhook_url" not in read_settings_history()[0]["changes"]


def test_feed_redaction_blanks_only_the_passkey():
    """A public feed's own query (search, category) must survive an export,
    or two feeds of the same site collapse into one unusable URL."""
    data = redact_settings_dict(
        {
            "rss_feeds": [
                {"url": "https://nyaa.si/?page=rss&q=ubuntu&c=0_0&f=0"},
                {"url": "https://t.invalid/rss?u=1&passkey=SECRET&cat=5"},
                {"url": "https://www.torrentleech.org/rss/0123456789abcdef0123456789abcdef"},
            ]
        }
    )

    assert [feed["url"] for feed in data["rss_feeds"]] == [
        "https://nyaa.si/?page=rss&q=ubuntu&c=0_0&f=0",
        "https://t.invalid/rss?u=1&passkey=&cat=5",
        "https://www.torrentleech.org/rss/",
    ]


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


def test_a_live_save_after_an_import_does_not_overwrite_it(tmp_path, monkeypatch):
    """The import applies on the next launch: until then the running Settings
    (still the pre-import state) must not be written back over it."""
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    settings = Settings.load()  # first save: language "fr" in memory and on disk
    imported = tmp_path / "import.json"
    imported.write_text(json.dumps({"language": "ja"}), encoding="utf-8")
    assert ProfileSecurityBridge(settings).importConfig(str(imported))["ok"]

    settings.audio_volume = 10  # what setVolume does
    settings.save()

    assert Settings.load().language == "ja"
    assert read_settings_history() == []


def test_import_refuses_a_json_object_that_is_not_a_torrent2000_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    settings = Settings.load()
    foreign = tmp_path / "package.json"
    foreign.write_text(json.dumps({"name": "some-other-app", "version": "1.0", "dependencies": {}}), encoding="utf-8")
    before = get_config_path().read_text(encoding="utf-8")

    assert ProfileSecurityBridge(settings).importConfig(str(foreign))["ok"] is False
    assert get_config_path().read_text(encoding="utf-8") == before  # all settings reset to defaults otherwise
