"""Volume serial number and label for the drive containing a path -- used to
recognize "the same physical drive is back"/"this specific drive was
registered" without relying on a drive letter alone, which can be reused by
a completely different disk or reassigned across reboots. Windows-only
(GetVolumeInformationW), matching this project's Windows-only scope (see
disk_allocation.py for the same ctypes pattern).
"""

import ctypes
import os


def get_volume_serial(path: str) -> int | None:
    """Returns the volume serial number of the drive containing `path`, or
    None if it can't be determined (path has no drive, the query API isn't
    available, or the drive is currently unreachable -- e.g. the very
    external-drive disconnect this is meant to detect).

    GetVolumeInformationW requires a ROOT path (e.g. "E:\\"), not a
    subfolder -- splitdrive + a trailing separator gets there from any path
    on that drive.
    """
    drive, _ = os.path.splitdrive(path)
    if not drive:
        return None
    root = drive + "\\"
    serial = ctypes.c_uint32(0)
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(root, None, 0, ctypes.byref(serial), None, None, None, 0)
    except (AttributeError, OSError):
        return None
    if not ok:
        return None
    return serial.value


def get_volume_label(path: str) -> str | None:
    """Returns the volume label of the drive containing `path` (e.g.
    "BACKUP_USB"), or None if it can't be determined -- no drive in `path`,
    the drive is currently unreachable, the query API isn't available, or
    the drive simply has no label set (Windows returns an empty string in
    that case, treated the same as "unknown" here since an empty label could
    never usefully be registered as a known disk).

    Same GetVolumeInformationW call as get_volume_serial() above, just
    reading the name buffer instead of the serial number; requires a ROOT
    path (e.g. "E:\\"), not a subfolder -- same splitdrive handling.
    """
    drive, _ = os.path.splitdrive(path)
    if not drive:
        return None
    root = drive + "\\"
    name_buffer = ctypes.create_unicode_buffer(261)  # MAX_PATH + 1
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(root, name_buffer, 261, None, None, None, None, 0)
    except (AttributeError, OSError):
        return None
    if not ok:
        return None
    return name_buffer.value or None
