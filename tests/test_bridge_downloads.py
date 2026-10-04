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
