"""Shared by AddBridge and ShareBridge -- both have their own drop zone and
both need the same "write dropped bytes to a temp .torrent file" step (see
AddBridge.saveDroppedTorrent for why this exists instead of a real path)."""

import base64
import os
import tempfile

# A legitimate .torrent (even a large multi-file pack's metadata) is on the
# order of KB, not MB -- caps how much a hostile/buggy drop payload can force
# this process to decode and write to disk. Mirrors url_fetch.py's
# _MAX_RESPONSE_BYTES-style hardening for the same "an attacker controls the
# size" shape of input.
_MAX_TORRENT_BYTES = 8 * 1024 * 1024


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
