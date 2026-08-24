"""Tests for compressed_file_size (real on-disk allocated bytes vs. apparent
size). Real filesystem I/O, no mocking needed -- Windows GetCompressedFileSizeW
is exercised for real against a real uncompressed file (falls back to the
same value os.stat() reports, which is what we assert against)."""

from torrent2000.engine.disk_allocation import compressed_file_size


def test_missing_file_returns_zero(tmp_path):
    assert compressed_file_size(tmp_path / "does_not_exist.bin") == 0


def test_uncompressed_file_matches_apparent_size(tmp_path):
    path = tmp_path / "plain.bin"
    path.write_bytes(b"x" * 12345)

    assert compressed_file_size(path) == 12345


def test_empty_file_is_zero(tmp_path):
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")

    assert compressed_file_size(path) == 0
