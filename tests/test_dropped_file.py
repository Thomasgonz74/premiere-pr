"""Regression tests for the drop-zone hardening: size cap + forced .torrent
suffix regardless of the browser-supplied filename (see ui/web/dropped_file.py
and the pentest-style catalogue idea it closes)."""

import base64
import os

from torrent2000.ui.web.dropped_file import _MAX_TORRENT_BYTES, save_dropped_bytes_to_temp_file


def test_normal_torrent_bytes_are_written_with_torrent_suffix():
    data = b"d8:announce...e"  # not a real bencoded torrent, just some bytes
    path = save_dropped_bytes_to_temp_file("evil.exe", base64.b64encode(data).decode("ascii"))
    try:
        assert path != ""
        assert path.endswith(".torrent")
        with open(path, "rb") as f:
            assert f.read() == data
    finally:
        if path:
            os.remove(path)


def test_oversized_payload_is_rejected():
    data = b"x" * (_MAX_TORRENT_BYTES + 1)
    path = save_dropped_bytes_to_temp_file("big.torrent", base64.b64encode(data).decode("ascii"))
    assert path == ""


def test_invalid_base64_is_rejected_without_raising():
    assert save_dropped_bytes_to_temp_file("x.torrent", "not-valid-base64-!!!") == ""
