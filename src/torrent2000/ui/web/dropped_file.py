"""Shared by AddBridge and ShareBridge -- both have their own drop zone and
both need the same "write dropped bytes to a temp .torrent file" step (see
AddBridge.saveDroppedTorrent for why this exists instead of a real path)."""

import base64
import os
import tempfile
import time
from pathlib import Path

# A legitimate .torrent (even a large multi-file pack's metadata) is on the
# order of KB, not MB -- caps how much a hostile/buggy drop payload can force
# this process to decode and write to disk. Mirrors url_fetch.py's
# _MAX_RESPONSE_BYTES-style hardening for the same "an attacker controls the
# size" shape of input.
_MAX_TORRENT_BYTES = 8 * 1024 * 1024

# Every temp .torrent the app writes: this module's drops, remote_server.py's
# remote adds and rss_feed_service.py's downloads.
_TEMP_TORRENT_PREFIXES = ("dropped_", "remote_add_", "torrent2000_rss_")
_STALE_TEMP_TORRENT_SECONDS = 24 * 60 * 60


def save_dropped_bytes_to_temp_file(filename: str, base64_data: str) -> str:
    """Returns the temp file path, or "" if the payload is oversized/not
    valid base64 -- callers already treat an empty/unreadable path as a
    normal "couldn't read this file" error (see AddBridge.selectTorrentFile).
    The suffix is always forced to .torrent regardless of the
    browser-supplied `filename`, which is untrusted client input."""
    try:
        data = base64.b64decode(base64_data, validate=True)
    except (ValueError, TypeError):
        return ""
    if len(data) > _MAX_TORRENT_BYTES:
        return ""
    fd, path = tempfile.mkstemp(suffix=".torrent", prefix="dropped_")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def cleanup_stale_temp_torrents() -> None:
    """Best-effort removal of temp .torrent files more than a day old, run
    once per launch (same idea as update_checker._cleanup_stale_installers).
    RSS and remote adds delete their file right after the add, but a dropped
    file can't be: its path is used until the user clicks Start on the Add
    page, possibly never -- and a crash or a brief Windows lock can orphan
    any of the three. Failures (a file still in use) are swallowed; the
    next launch retries."""
    cutoff = time.time() - _STALE_TEMP_TORRENT_SECONDS
    for stale in Path(tempfile.gettempdir()).glob("*.torrent"):
        if not stale.name.startswith(_TEMP_TORRENT_PREFIXES):
            continue
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass
