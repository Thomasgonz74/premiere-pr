"""Minimal coverage for the restorable settings-history log: Settings.save()
journals a diff to config_backups/history.jsonl, excludes sensitive fields,
and a past entry can be restored.
"""

import json
from pathlib import Path

from torrent2000.config.paths import get_config_backups_dir, get_config_path
from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.config.settings_history import read_settings_history, restore_settings_snapshot


def test_save_journals_diff_and_excludes_sensitive_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))

    settings = Settings.load()  # first-ever save: no prior state, nothing journaled yet
    assert read_settings_history() == []

    settings.language = "ja"
    settings.proxy.enabled = True
    settings.remote_access_token = "super-secret-token"
    settings.save()

    history = read_settings_history()
    assert len(history) == 1
    changes = history[0]["changes"]
    assert changes["language"] == {"old": "fr", "new": "ja"}
    assert "proxy" not in changes
    assert "remote_access_token" not in changes


def test_history_most_recent_first(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))

    settings = Settings.load()
    settings.language = "ja"
    settings.save()
    settings.language = "en"
    settings.save()

    history = read_settings_history()
    assert len(history) == 2
    assert history[0]["changes"]["language"] == {"old": "ja", "new": "en"}
    assert history[1]["changes"]["language"] == {"old": "fr", "new": "ja"}


def test_restore_settings_snapshot_reverts_field(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))

    settings = Settings.load()
    settings.language = "ja"
    settings.save()

    entry = read_settings_history()[0]
    restore_settings_snapshot(entry, settings)

    assert settings.language == "fr"
    reloaded = Settings.load()
    assert reloaded.language == "fr"


def test_restore_rebuilds_nested_dataclass_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))

    settings = Settings.load()
    settings.bandwidth_schedule.enabled = True
    settings.bandwidth_schedule.start_hour = 2
    settings.save()

    entry = read_settings_history()[0]
    restore_settings_snapshot(entry, settings)

    assert settings.bandwidth_schedule.enabled is False
    assert settings.bandwidth_schedule.start_hour == 8


def test_save_diffs_without_rereading_config_or_history(tmp_path, monkeypatch):
    """Reopening config.json / history.jsonl right after writing them
    triggers a Defender scan (~14 ms of a ~19 ms save): the diff base is kept
    in memory and the history size comes from f.tell()."""
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    settings = Settings.load()
    reads = []
    real_read_text = Path.read_text
    with monkeypatch.context() as m:
        m.setattr(Path, "read_text", lambda self, *a, **k: (reads.append(self.name), real_read_text(self, *a, **k))[1])
        settings.language = "ja"
        settings.save()
        settings.language = "en"
        settings.save()

    assert reads == []
    assert [e["changes"]["language"] for e in read_settings_history()] == [
        {"old": "ja", "new": "en"},
        {"old": "fr", "new": "ja"},
    ]


def test_first_save_after_an_upgrade_journals_only_what_the_user_changed(tmp_path, monkeypatch):
    """A config written by an older version lacks the fields added since:
    the first save must not journal them all, rss_feeds (passkeys) included."""
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    feed = {"url": "https://tracker.invalid/rss?passkey=SECRET", "filter_keyword": "", "enabled": True}
    get_config_path().write_text(json.dumps({"default_download_dir": "D:/dl", "rss_feeds": [feed]}), encoding="utf-8")

    settings = Settings.load()
    settings.audio_volume = 42
    settings.save()

    assert list(read_settings_history()[0]["changes"]) == ["audio_volume"]


def test_history_redacts_feed_passkeys_and_restore_keeps_live_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))

    settings = Settings.load()
    settings.rss_feeds = [RssFeedSubscription(url="https://t.invalid/rss?passkey=SECRET", filter_keyword="old")]
    settings.save()
    settings.rss_feeds[0].filter_keyword = "new"
    settings.rss_feeds.append(RssFeedSubscription(url="https://u.invalid/rss/0123456789abcdef0123456789abcdef"))
    settings.save()

    history_text = (get_config_backups_dir() / "history.jsonl").read_text(encoding="utf-8")
    assert "SECRET" not in history_text and "0123456789abcdef" not in history_text

    restore_settings_snapshot(read_settings_history()[0], settings)

    assert [(feed.url, feed.filter_keyword) for feed in settings.rss_feeds] == [
        ("https://t.invalid/rss?passkey=SECRET", "old")
    ]


def test_restore_puts_back_a_public_feed_url_and_pairs_feeds_by_position_only_on_one_host(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    settings = Settings.load()
    settings.rss_feeds = [
        RssFeedSubscription(url="https://a.invalid/user/111.rss", filter_keyword="show-a"),
        RssFeedSubscription(url="https://b.invalid/rss?cat=1&passkey=SECRET", filter_keyword="show-b"),
    ]
    settings.save()
    settings.rss_feeds = [
        RssFeedSubscription(url="https://c.invalid/rss", filter_keyword="show-c"),
        RssFeedSubscription(url="https://b.invalid/rss?cat=2&passkey=SECRET", filter_keyword="show-b2"),
    ]
    settings.save()

    restore_settings_snapshot(read_settings_history()[0], settings)

    # The public URL was kept whole, so it comes back; the private one only
    # redacted, so its feed keeps the live URL on the same host.
    assert [(feed.url, feed.filter_keyword) for feed in settings.rss_feeds] == [
        ("https://a.invalid/user/111.rss", "show-a"),
        ("https://b.invalid/rss?cat=2&passkey=SECRET", "show-b"),
    ]
