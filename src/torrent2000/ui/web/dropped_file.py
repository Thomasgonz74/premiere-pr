"""Shared by AddBridge and ShareBridge -- both have their own drop zone and
both need the same "write dropped bytes to a temp .torrent file" step (see
AddBridge.saveDroppedTorrent for why this exists instead of a real path)."""

import base64
import os
import tempfile


def save_dropped_bytes_to_temp_file(filename: str, base64_data: str) -> str:
    suffix = os.path.splitext(filename)[1] or ".torrent"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="dropped_")
    with os.fdopen(fd, "wb") as f:
        f.write(base64.b64decode(base64_data))
    return path
