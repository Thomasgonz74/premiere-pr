import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


def _session_manager_with_record(record: TorrentRecord) -> MagicMock:
    sm = MagicMock()
    sm.get_record.return_value = record
    return sm


# --------------------------------------------------------------- ratio limit


def test_ratio_limit_pauses_once_ratio_reached():
    record = TorrentRecord(info_hash="abc123", name="x", save_path="C:\\x", all_time_uploaded=0, all_time_downloaded=0)
    sm = _session_manager_with_record(record)
    service = ShareLimitService(sm, Settings())
    service.track("abc123", time_limit_seconds=None, data_limit_bytes=None, ratio_limit=1.5)

    below_ratio = TorrentRecord(
        info_hash="abc123", name="x", save_path="C:\\x", all_time_uploaded=100, all_time_downloaded=100
    )
    service._on_status_updated("abc123", below_ratio)
    assert service.limit_for("abc123").reached is False
    sm.pause_torrent.assert_not_called()

    at_ratio = TorrentRecord(
        info_hash="abc123", name="x", save_path="C:\\x", all_time_uploaded=200, all_time_downloaded=100
    )
    received = []
    service.limit_reached.connect(lambda info_hash, reason: received.append((info_hash, reason)))
    service._on_status_updated("abc123", at_ratio)

    limit = service.limit_for("abc123")
    assert limit.reached is True
    assert limit.reached_reason == "ratio"
    sm.pause_torrent.assert_called_once_with("abc123")
    assert received == [("abc123", "ratio")]


def test_ratio_limit_triggers_for_data_already_on_disk_with_nothing_downloaded():
    # Torrent added via the Partage tab pointing at data already on disk
    # (e.g. "Dossier contenant deja les fichiers"): libtorrent hash-checks
    # the local files but never reports that as "downloaded", so
    # all_time_downloaded stays 0 for the torrent's whole lifetime even
    # though it is fully present and being seeded. The ratio cap must still
    # be able to fire in this case, using the verified local size as the
    # denominator.
    record = TorrentRecord(
        info_hash="abc123",
        name="x",
        save_path="C:\\x",
        total_size=4_194_304,
        progress=1.0,
        state=TorrentState.SEEDING,
        all_time_uploaded=0,
        all_time_downloaded=0,
    )
    sm = _session_manager_with_record(record)
    service = ShareLimitService(sm, Settings())
    service.track("abc123", time_limit_seconds=None, data_limit_bytes=None, ratio_limit=0.5)

    below_ratio = TorrentRecord(
        info_hash="abc123", name="x", save_path="C:\\x", total_size=4_194_304, progress=1.0,
        state=TorrentState.SEEDING, all_time_uploaded=1_000_000, all_time_downloaded=0,
    )
    service._on_status_updated("abc123", below_ratio)
    assert service.limit_for("abc123").reached is False
    sm.pause_torrent.assert_not_called()

    at_ratio = TorrentRecord(
        info_hash="abc123", name="x", save_path="C:\\x", total_size=4_194_304, progress=1.0,
        state=TorrentState.SEEDING, all_time_uploaded=4_194_304, all_time_downloaded=0,
    )
    service._on_status_updated("abc123", at_ratio)

    limit = service.limit_for("abc123")
    assert limit.reached is True
    assert limit.reached_reason == "ratio"
    sm.pause_torrent.assert_called_once_with("abc123")


def test_ratio_limit_ignored_while_nothing_downloaded_yet():
    # A fresh torrent with all_time_downloaded == 0 must not divide-by-zero
    # or spuriously trip the ratio cap just because uploaded > 0 (e.g. re-
    # seeding data already on disk before libtorrent reports any download).
    record = TorrentRecord(info_hash="abc123", name="x", save_path="C:\\x", all_time_uploaded=50, all_time_downloaded=0)
    sm = _session_manager_with_record(record)
    service = ShareLimitService(sm, Settings())
    service.track("abc123", time_limit_seconds=None, data_limit_bytes=None, ratio_limit=1.0)

    service._on_status_updated("abc123", record)

    assert service.limit_for("abc123").reached is False
    sm.pause_torrent.assert_not_called()


# ---------------------------------------------------- default share policy


def test_apply_default_policy_tracks_a_newly_seeding_torrent_when_enabled():
    settings = Settings(
        default_share_policy_enabled=True,
        default_share_time_limit_hours=2,
        default_share_data_limit_mb=500,
        default_share_ratio_limit=1.0,
    )
    record = TorrentRecord(info_hash="abc123", name="x", save_path="C:\\x", state=TorrentState.SEEDING)
    sm = _session_manager_with_record(record)
    service = ShareLimitService(sm, settings)

    service._on_status_updated("abc123", record)

    assert service.is_tracked("abc123")
    limit = service.limit_for("abc123")
    assert limit.time_limit_seconds == 2 * 3600
    assert limit.data_limit_bytes == 500 * 1024 * 1024
    assert limit.ratio_limit == 1.0


def test_apply_default_policy_does_nothing_when_disabled():
    record = TorrentRecord(info_hash="abc123", name="x", save_path="C:\\x", state=TorrentState.SEEDING)
    sm = _session_manager_with_record(record)
    service = ShareLimitService(sm, Settings())  # default_share_policy_enabled is False by default

    service._on_status_updated("abc123", record)

    assert not service.is_tracked("abc123")


def test_apply_default_policy_does_not_override_an_already_tracked_torrent():
    settings = Settings(default_share_policy_enabled=True, default_share_time_limit_hours=2)
    record = TorrentRecord(info_hash="abc123", name="x", save_path="C:\\x", state=TorrentState.SEEDING)
    sm = _session_manager_with_record(record)
    service = ShareLimitService(sm, settings)
    service.track("abc123", time_limit_seconds=99, data_limit_bytes=None, ratio_limit=None)

    service.apply_default_policy_if_enabled("abc123")

    assert service.limit_for("abc123").time_limit_seconds == 99


def test_apply_default_policy_only_triggers_on_seeding_transition():
    settings = Settings(default_share_policy_enabled=True, default_share_time_limit_hours=1)
    record = TorrentRecord(info_hash="abc123", name="x", save_path="C:\\x", state=TorrentState.DOWNLOADING)
    sm = _session_manager_with_record(record)
    service = ShareLimitService(sm, settings)

    service._on_status_updated("abc123", record)

    assert not service.is_tracked("abc123")
