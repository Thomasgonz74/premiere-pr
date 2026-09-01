"""Minimal coverage for peer_reputation.py (opt-in, off by default -- see
Settings.peer_reputation_enabled): store persistence (tmp+os.replace, mirrors
test_known_disk_service.py's isolated_data_dir pattern), disconnect-driven
tracking (duration/bytes/hashfails folded in only once a peer disappears from
a snapshot), and the score_label heuristic. No QApplication needed -- this
module has no QObject/Signal, unlike known_disk_service.py's service class.
"""

import pytest

from torrent2000.engine.peer_reputation import (
    PeerReputationRecord,
    PeerReputationStore,
    PeerReputationTracker,
    ip_from_display,
    score_label,
)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class FakePeer:
    def __init__(self, ip, port, total_download, num_hashfails):
        self.ip = (ip, port)
        self.total_download = total_download
        self.num_hashfails = num_hashfails


# ----------------------------------------------------------------- PeerReputationStore


def test_store_starts_empty_when_no_file_exists():
    assert PeerReputationStore().get("1.2.3.4") is None


def test_record_disconnect_persists_and_accumulates_across_streaks():
    store = PeerReputationStore()
    store.record_disconnect("1.2.3.4", connected_seconds=30.0, bytes_received=1000, hashfails=0)
    store.record_disconnect("1.2.3.4", connected_seconds=90.0, bytes_received=2000, hashfails=1)

    reloaded = PeerReputationStore()
    rec = reloaded.get("1.2.3.4")
    assert rec.disconnect_count == 2
    assert rec.total_connected_seconds == 120.0
    assert rec.total_bytes_received == 3000
    assert rec.total_hashfails == 1


def test_ip_from_display_strips_trailing_port_including_ipv6():
    assert ip_from_display("203.0.113.7:6881") == "203.0.113.7"
    assert ip_from_display("fe80::1:6881") == "fe80::1"


# --------------------------------------------------------------- PeerReputationTracker


def test_tracker_only_folds_in_a_streak_once_the_peer_disappears():
    store = PeerReputationStore()
    tracker = PeerReputationTracker(store)

    tracker.observe("hashA", [FakePeer("1.2.3.4", 6881, 500, 0)])
    assert store.get("1.2.3.4") is None  # still connected -- nothing folded in yet

    tracker.observe("hashA", [FakePeer("1.2.3.4", 6881, 1500, 0)])
    assert store.get("1.2.3.4") is None  # still there, higher counters -- still not disconnected

    tracker.observe("hashA", [])  # gone this tick
    rec = store.get("1.2.3.4")
    assert rec.disconnect_count == 1
    assert rec.total_bytes_received == 1500  # last-seen total_download, not summed per-tick


def test_tracker_keys_active_streaks_per_torrent_not_globally():
    store = PeerReputationStore()
    tracker = PeerReputationTracker(store)

    tracker.observe("hashA", [FakePeer("9.9.9.9", 6881, 10, 0)])
    tracker.observe("hashB", [FakePeer("9.9.9.9", 6881, 20, 0)])
    tracker.observe("hashA", [])  # hashA's tick going empty must not disconnect hashB's view of 9.9.9.9

    assert store.get("9.9.9.9") is not None  # hashA's streak did get folded in
    assert store.get("9.9.9.9").disconnect_count == 1
    assert "9.9.9.9" in tracker._active.get("hashB", {})  # hashB's streak is untouched


# ----------------------------------------------------------------------- score_label


def test_score_label_neutral_with_no_data():
    assert score_label(None) == "neutral"
    assert score_label(PeerReputationRecord(ip="1.2.3.4")) == "neutral"


def test_score_label_bad_on_any_hashfail_regardless_of_duration():
    rec = PeerReputationRecord(ip="1.2.3.4", disconnect_count=1, total_connected_seconds=300, total_hashfails=1)
    assert score_label(rec) == "bad"


def test_score_label_good_requires_stable_duration_and_data():
    rec = PeerReputationRecord(
        ip="1.2.3.4", disconnect_count=1, total_connected_seconds=120, total_bytes_received=1000
    )
    assert score_label(rec) == "good"

    short_rec = PeerReputationRecord(
        ip="1.2.3.4", disconnect_count=1, total_connected_seconds=5, total_bytes_received=1000
    )
    assert score_label(short_rec) == "neutral"
