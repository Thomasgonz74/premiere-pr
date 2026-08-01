from torrent2000.engine.bandwidth_scheduler import is_within_window


def test_normal_daytime_window():
    assert is_within_window(10, 8, 22) is True
    assert is_within_window(8, 8, 22) is True  # inclusive start
    assert is_within_window(22, 8, 22) is False  # exclusive end
    assert is_within_window(7, 8, 22) is False
    assert is_within_window(23, 8, 22) is False


def test_window_wrapping_past_midnight():
    # 22:00 - 06:00 overnight window
    assert is_within_window(23, 22, 6) is True
    assert is_within_window(2, 22, 6) is True
    assert is_within_window(6, 22, 6) is False  # exclusive end
    assert is_within_window(22, 22, 6) is True  # inclusive start
    assert is_within_window(12, 22, 6) is False


def test_zero_width_window_never_applies():
    assert is_within_window(10, 8, 8) is False


def test_full_day_window():
    # start=0, end=24 isn't valid (hours are 0-23), but start=0,end=0 with
    # wraparound semantics would be zero-width (never applies) per above;
    # a "basically always on" schedule should instead use a very wide
    # explicit range, which callers can already express with 0/23.
    assert is_within_window(0, 0, 23) is True
    assert is_within_window(23, 0, 23) is False
