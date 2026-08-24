"""Real on-disk allocated size for a file, as opposed to its logical/apparent
size -- differs on a compressed or sparse NTFS volume, or when the disk
couldn't fully allocate a file marked complete. Windows-only (GetCompressedFileSizeW),
matching this project's Windows-only scope (see packaging/torrent2000_installer.iss).
"""

import ctypes
from pathlib import Path

_INVALID_FILE_SIZE = 0xFFFFFFFF


def compressed_file_size(path: Path) -> int:
    """Falls back to the file's apparent size (path.stat().st_size) if the
    compressed-size query fails, or if the file doesn't exist yet (a piece
    not downloaded yet has no real allocation to report)."""
    if not path.exists():
        return 0
    high = ctypes.c_uint32(0)
    try:
        low = ctypes.windll.kernel32.GetCompressedFileSizeW(str(path), ctypes.byref(high))
    except (AttributeError, OSError):
        low = _INVALID_FILE_SIZE
    if low == _INVALID_FILE_SIZE:
        try:
            return path.stat().st_size
        except OSError:
            return 0
    return (high.value << 32) + low
