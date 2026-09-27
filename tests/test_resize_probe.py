from torrent2000.ui.web.resize_probe import summarize


def test_summarize_matches_each_step_to_first_frame_at_that_size():
    steps = [(100.0, 800, 600), (110.0, 810, 600), (120.0, 820, 600)]
    frames = [(90.0, 800, 600), (135.0, 810, 600), (160.0, 830, 600), (170.0, 820, 600)]
    r = summarize(steps, frames, enter_t=95.0, exit_t=125.0)
    # 800 was already painted before its step -> not a match; 810 at +25 ms,
    # 820 at +50 ms; the stale 800 frame at t=90 must not count.
    assert r["resize_steps"] == 3
    assert r["steps_never_rendered"] == 1
    assert r["lag_ms_p50"] == 37.5
    assert r["lag_ms_max"] == 50.0
    assert r["final_frame_after_release_ms"] == 45.0
    assert r["chromium_frames"] == 0  # 135 and later are after exit
    assert r["step_gap_ms_p50"] == 10.0
    assert r["step_rate_hz"] == 100.0  # 3 steps in 30 ms


def test_summarize_frozen_gesture_has_no_lag_but_reports_settle():
    steps = [(10.0, 700, 500), (20.0, 720, 500)]
    frames = [(95.0, 720, 500)]
    r = summarize(steps, frames, enter_t=0.0, exit_t=30.0)
    assert r["steps_never_rendered"] == 1
    assert r["final_frame_after_release_ms"] == 65.0
