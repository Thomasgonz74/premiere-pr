"""Tests for get_volume_serial. Real filesystem I/O, no mocking needed --
Windows GetVolumeInformationW is exercised for real against tmp_path's actual
drive, matching test_disk_allocation.py's style for the same ctypes-wrapper
pattern."""

from torrent2000.engine.volume_serial import get_volume_serial


def test_real_path_returns_an_int_serial(tmp_path):
    serial = get_volume_serial(str(tmp_path))
    assert isinstance(serial, int)


def test_serial_is_stable_for_the_same_drive(tmp_path):
    assert get_volume_serial(str(tmp_path)) == get_volume_serial(str(tmp_path))


def test_path_without_a_drive_returns_none():
    assert get_volume_serial("relative/path/no_drive") is None


def test_empty_path_returns_none():
    assert get_volume_serial("") is None
