"""Minimal coverage for the restorable settings-history log: Settings.save()
journals a diff to config_backups/history.jsonl, excludes sensitive fields,
and a past entry can be restored.
"""

from pathlib import Path

from torrent2000.config.settings import Settings
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
