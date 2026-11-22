from unittest.mock import MagicMock

from PySide6.QtCore import QObject, Signal

from torrent2000.engine.tag_service import TagService
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState, TrackerInfo
from torrent2000.ui.web.bridge_downloads import DownloadsBridge, _compute_slowness_causes, _record_to_dict


def _downloading_record(info_hash="h1", **overrides) -> TorrentRecord:
    return TorrentRecord(info_hash=info_hash, state=TorrentState.DOWNLOADING, **overrides)


def test_no_seeds_is_flagged():
    record = _downloading_record(num_seeds=0)
    causes = _compute_slowness_causes(record, [record], download_limit_kbps=0)
    assert [c["code"] for c in causes] == ["no_seeds"]


def test_tracker_error_is_flagged():
    record = _downloading_record(
        num_seeds=5,
        trackers=[TrackerInfo(url="udp://tracker.example", last_error="connection timed out")],
    )
    causes = _compute_slowness_causes(record, [record], download_limit_kbps=0)
    assert [c["code"] for c in causes] == ["tracker_error"]
    assert "tracker.example" in causes[0]["text"]


def test_tracker_without_error_is_not_flagged():
    record = _downloading_record(num_seeds=5, trackers=[TrackerInfo(url="udp://tracker.example")])
    causes = _compute_slowness_causes(record, [record], download_limit_kbps=0)
    assert causes == []


def test_bandwidth_limit_inferred_when_near_cap_and_others_active():
    record = _downloading_record(num_seeds=5, download_rate=95 * 1024)  # 95 KB/s
    other = _downloading_record(info_hash="h2")
    causes = _compute_slowness_causes(record, [record, other], download_limit_kbps=100)
    assert [c["code"] for c in causes] == ["bandwidth_limit"]


def test_bandwidth_limit_not_inferred_when_no_other_torrent_active():
    record = _downloading_record(num_seeds=5, download_rate=95 * 1024)
    causes = _compute_slowness_causes(record, [record], download_limit_kbps=100)
    assert causes == []


def test_bandwidth_limit_not_inferred_when_far_from_cap():
    record = _downloading_record(num_seeds=5, download_rate=10 * 1024)
    other = _downloading_record(info_hash="h2")
    causes = _compute_slowness_causes(record, [record, other], download_limit_kbps=100)
    assert causes == []


def test_bandwidth_limit_not_inferred_when_unlimited():
    record = _downloading_record(num_seeds=5, download_rate=10_000 * 1024)
    other = _downloading_record(info_hash="h2")
    causes = _compute_slowness_causes(record, [record, other], download_limit_kbps=0)
    assert causes == []


def test_record_to_dict_exposes_pinned_flag():
    assert _record_to_dict(_downloading_record(pinned=True))["pinned"] is True
    assert _record_to_dict(_downloading_record(pinned=False))["pinned"] is False


def test_multiple_causes_can_combine():
    record = _downloading_record(
        num_seeds=0,
        download_rate=95 * 1024,
        trackers=[TrackerInfo(url="udp://tracker.example", last_error="unreachable")],
    )
    other = _downloading_record(info_hash="h2")
    causes = _compute_slowness_causes(record, [record, other], download_limit_kbps=100)
    assert [c["code"] for c in causes] == ["no_seeds", "tracker_error", "bandwidth_limit"]


class _FakeSessionManager(QObject):
    torrent_added = Signal(str)
    torrent_status_batch_updated = Signal(list)
    torrent_removed = Signal(str)
    torrent_restore_failed = Signal(str)
    ip_blocklist_wait_changed = Signal(bool)
    waiting_for_ip_blocklist = False

    def is_waiting_for_ip_blocklist(self):
        return self.waiting_for_ip_blocklist


def test_ip_blocklist_wait_is_relayed_and_readable_by_a_late_page():
    session_manager = _FakeSessionManager()
    bridge = DownloadsBridge(session_manager, MagicMock())
    relayed = []
    bridge.ipBlocklistWaitChanged.connect(relayed.append)

    session_manager.waiting_for_ip_blocklist = True
    assert bridge.isWaitingForIpBlocklist() is True
    session_manager.ip_blocklist_wait_changed.emit(False)

    assert relayed == [False]


def test_removing_a_torrent_clears_its_tags(tmp_path, monkeypatch):
    """Like its category, a removed torrent's tags must not linger in
    tags.json or in the tag filter (a re-added torrent starts untagged)."""
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    tags = TagService()
    tags.add("h1", "linux")
    tags.add("h2", "iso")
    session_manager = _FakeSessionManager()
    bridge = DownloadsBridge(session_manager, MagicMock(), tag_service=tags)

    session_manager.torrent_removed.emit("h1")

    assert bridge.listAllTags() == ["iso"]
    assert TagService().get("h1") == []  # persisted, not just in memory


def test_resuming_a_magnet_awaiting_analysis_starts_it_after_its_scan_and_says_so():
    session_manager = MagicMock()
    session_manager.get_record.return_value = TorrentRecord(info_hash="h1", awaiting_analysis=True)
    bridge = DownloadsBridge(session_manager, MagicMock())
    announced = []
    bridge.awaitingMagnetStarted.connect(lambda: announced.append(True))

    bridge.resumeTorrent("h1")

    session_manager.start_awaiting_magnet.assert_called_once_with("h1")
    session_manager.resume_torrent.assert_not_called()
    assert announced == [True]


def test_starting_a_held_magnet_whose_metadata_is_in_says_nothing_more():
    """Started at once (or blocked by the CCCP theme, which says so itself):
    no "will start once its metadata arrives" banner."""
    session_manager = MagicMock()
    session_manager.get_record.return_value = TorrentRecord(info_hash="h1", awaiting_analysis=True)
    session_manager.start_awaiting_magnet.return_value = False
    bridge = DownloadsBridge(session_manager, MagicMock())
    announced = []
    bridge.awaitingMagnetStarted.connect(lambda: announced.append(True))

    bridge.resumeTorrent("h1")

    assert announced == []


def test_pinning_or_categorising_an_idle_torrent_updates_its_row_at_once():
    """No status tick reports an idle torrent, nor a pin libtorrent knows
    nothing of: the row kept its old pin (a second click pinned it again)."""
    record = TorrentRecord(info_hash="h1", state=TorrentState.SEEDING)
    session_manager = MagicMock()
    session_manager.get_record.return_value = record
    session_manager.pin_torrent.side_effect = lambda ih: setattr(record, "pinned", True)
    session_manager.set_torrent_category.side_effect = lambda ih, category: setattr(record, "category", category)
    bridge = DownloadsBridge(session_manager, MagicMock())
    pushed = []
    bridge.recordUpdated.connect(lambda row: pushed.append((row["pinned"], row["category"])))

    bridge.pinTorrent("h1")
    bridge.setCategory("h1", "Docs")

    assert pushed == [(True, ""), (True, "Docs")]


def test_a_move_to_a_drive_root_is_refused_with_a_message_for_the_page(tmp_path):
    """Its only feedback was a tray toast, and none with notifications off."""
    from torrent2000.i18n.translator import tr

    session_manager = MagicMock()
    session_manager.get_record.return_value = TorrentRecord(info_hash="h1", name="HotelFile")
    bridge = DownloadsBridge(session_manager, MagicMock())

    refusal = bridge.moveStorage("h1", "D:/")

    assert refusal == tr("notifications.move_storage_refused_message", name="HotelFile", path="D:/")
    session_manager.move_storage.assert_not_called()
    assert bridge.moveStorage("h1", str(tmp_path / "films")) == ""  # under way
    session_manager.move_storage.assert_called_once_with("h1", str(tmp_path / "films"))


def test_the_slowness_explanation_follows_the_language():
    import json
    from pathlib import Path

    from torrent2000.i18n import translator

    english = json.loads(
        (Path(__file__).resolve().parents[1] / "resources" / "i18n" / "en.json").read_text(encoding="utf-8")
    )
    record = _downloading_record(num_seeds=0, trackers=[TrackerInfo(url="udp://t.example", last_error="timed out")])
    session_manager = MagicMock()
    session_manager.get_record.return_value = record
    session_manager.all_records.return_value = [record]
    scheduler = MagicMock()
    scheduler.current_download_limit_kbps.return_value = 0
    bridge = DownloadsBridge(session_manager, scheduler)
    translator.set_language("en")
    try:
        result = bridge.explainSlowness("h1")
    finally:
        translator.set_language(translator.DEFAULT_LANGUAGE)

    assert [cause["text"] for cause in result["causes"]] == [
        english["web.downloads.slowness_no_seeds"],
        english["web.downloads.slowness_tracker_error"].format(url="udp://t.example", error="timed out"),
    ]
    assert result["note"] == english["web.downloads.slowness_encryption_note"]
