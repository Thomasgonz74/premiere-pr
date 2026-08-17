"""Boundary-case coverage for the pure human_* formatting helpers."""

import pytest

from torrent2000.utils.formatting import human_eta, human_percent, human_rate, human_size

# --------------------------------------------------------------- human_size


def test_human_size_zero_bytes():
    assert human_size(0) == "0 o"


def test_human_size_just_under_the_first_unit_threshold_stays_in_bytes():
    assert human_size(1023) == "1023 o"


def test_human_size_exactly_at_the_first_unit_threshold_promotes_to_ko():
    assert human_size(1024) == "1.00 Ko"


def test_human_size_just_under_the_second_unit_threshold_stays_in_ko():
    # The unit itself doesn't promote to Mo (1024*1024-1 divided once is still
    # < 1024), but rounding to two decimals during formatting displays it as
    # "1024.00 Ko" rather than "1023.99 Ko" -- a real, worth-knowing quirk.
    assert human_size(1024 * 1024 - 1) == "1024.00 Ko"


def test_human_size_exactly_at_the_second_unit_threshold_promotes_to_mo():
    assert human_size(1024 * 1024) == "1.00 Mo"


def test_human_size_exactly_at_the_go_threshold():
    assert human_size(1024**3) == "1.00 Go"


def test_human_size_exactly_at_the_to_threshold():
    assert human_size(1024**4) == "1.00 To"


def test_human_size_beyond_the_largest_unit_stays_in_to_instead_of_overflowing():
    assert human_size(1024**5) == "1024.00 To"


# --------------------------------------------------------------- human_rate


def test_human_rate_appends_per_second_suffix_to_human_size():
    assert human_rate(0) == "0 o/s"
    assert human_rate(2048) == "2.00 Ko/s"


# ---------------------------------------------------------------- human_eta


def test_human_eta_none_is_unknown():
    assert human_eta(None) == "—"


def test_human_eta_negative_is_unknown():
    assert human_eta(-1) == "—"


def test_human_eta_infinite_is_unknown():
    assert human_eta(float("inf")) == "—"


def test_human_eta_zero_seconds():
    assert human_eta(0) == "0s"


def test_human_eta_seconds_only_just_under_a_minute():
    assert human_eta(59) == "59s"


def test_human_eta_minutes_and_seconds():
    assert human_eta(65) == "1m 05s"


def test_human_eta_just_under_an_hour_stays_in_minutes():
    assert human_eta(3599) == "59m 59s"


def test_human_eta_exactly_one_hour():
    assert human_eta(3600) == "1h 00m"


def test_human_eta_hours_and_minutes():
    assert human_eta(3661) == "1h 01m"


# ------------------------------------------------------------ human_percent


@pytest.mark.parametrize(
    ("progress", "expected"),
    [
        (0.0, "0.0%"),
        (0.333, "33.3%"),
        (0.5, "50.0%"),
        (1.0, "100.0%"),
    ],
)
def test_human_percent(progress, expected):
    assert human_percent(progress) == expected
