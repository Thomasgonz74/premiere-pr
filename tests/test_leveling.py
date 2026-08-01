from torrent2000.stats.leveling import (
    LEVEL_BASE_BYTES,
    level_for_total_bytes,
    progress_within_level,
    snapshot,
    threshold_for_level,
)


def test_threshold_level_zero_is_zero():
    assert threshold_for_level(0) == 0


def test_threshold_level_one_is_one_gib():
    assert threshold_for_level(1) == LEVEL_BASE_BYTES


def test_threshold_grows_by_40_percent_each_level():
    # threshold_for_level computes 1.4**n directly rather than by repeated
    # multiplication, so tiny floating-point rounding differences (off by a
    # handful of bytes on multi-billion-byte values) are expected -- assert
    # the ratio is right, not bit-exact equality with an iterative recompute.
    for level in range(1, 30):
        ratio = threshold_for_level(level + 1) / threshold_for_level(level)
        assert abs(ratio - 1.4) < 1e-9


def test_thresholds_are_strictly_increasing():
    thresholds = [threshold_for_level(n) for n in range(0, 40)]
    assert thresholds == sorted(thresholds)
    assert len(set(thresholds)) == len(thresholds)


def test_level_zero_below_one_gib():
    assert level_for_total_bytes(0) == 0
    assert level_for_total_bytes(LEVEL_BASE_BYTES - 1) == 0


def test_level_one_at_exactly_one_gib():
    assert level_for_total_bytes(LEVEL_BASE_BYTES) == 1


def test_level_for_total_bytes_matches_threshold_at_every_boundary():
    for level in range(0, 50):
        exact = threshold_for_level(level)
        assert level_for_total_bytes(exact) == level
        if exact > 0:
            assert level_for_total_bytes(exact - 1) == level - 1


def test_level_for_total_bytes_just_below_next_threshold():
    for level in range(1, 50):
        next_threshold = threshold_for_level(level + 1)
        assert level_for_total_bytes(next_threshold - 1) == level


def test_progress_within_level_at_boundaries():
    assert progress_within_level(threshold_for_level(3)) == 0.0
    just_before_next = threshold_for_level(4) - 1
    assert 0.0 < progress_within_level(just_before_next) <= 1.0


def test_progress_within_level_is_always_bounded():
    for total in range(0, LEVEL_BASE_BYTES * 5, LEVEL_BASE_BYTES // 7 + 1):
        p = progress_within_level(total)
        assert 0.0 <= p <= 1.0


def test_snapshot_combines_download_and_upload():
    snap = snapshot(LEVEL_BASE_BYTES // 2, LEVEL_BASE_BYTES // 2)
    assert snap.level == 1
    assert snap.total_downloaded == LEVEL_BASE_BYTES // 2
    assert snap.total_uploaded == LEVEL_BASE_BYTES // 2
    assert snap.current_threshold == threshold_for_level(1)
    assert snap.next_threshold == threshold_for_level(2)
