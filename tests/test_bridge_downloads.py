from torrent2000.engine.torrent_item import TorrentRecord, TorrentState, TrackerInfo
from torrent2000.ui.web.bridge_downloads import _compute_slowness_causes, _record_to_dict


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
