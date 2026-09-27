"""Regression tests for the drop-zone hardening: size cap + forced .torrent
suffix regardless of the browser-supplied filename (see ui/web/dropped_file.py
and the pentest-style catalogue idea it closes)."""

import base64
import os
import tempfile
import time

from torrent2000.ui.web.dropped_file import (
    _MAX_TORRENT_BYTES,
    cleanup_stale_temp_torrents,
    save_dropped_bytes_to_temp_file,
)


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


def test_startup_sweep_removes_only_the_apps_temp_torrents_older_than_a_day(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    stale = [tmp_path / name for name in ("dropped_a.torrent", "remote_add_b.torrent", "torrent2000_rss_c.torrent")]
    fresh = tmp_path / "dropped_pending_on_the_add_page.torrent"
    foreign = tmp_path / "another_app.torrent"
    two_days_ago = time.time() - 2 * 24 * 60 * 60
    for path in [*stale, fresh, foreign]:
        path.write_bytes(b"x")
    for path in [*stale, foreign]:
        os.utime(path, (two_days_ago, two_days_ago))

    cleanup_stale_temp_torrents()

    assert [path for path in stale if path.exists()] == []
    assert fresh.exists()
    assert foreign.exists()
