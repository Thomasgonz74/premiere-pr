"""Optional confirmation prompt when a "known" disk is inserted (catalogue
"idees non implementees", cluster Automatisation contextuelle).

OFF BY DEFAULT (see Settings.known_disk_automation_enabled) -- and even once
enabled, this service NEVER acts on its own: check_now() only ever emits
diskConfirmationRequested with the disk's info and its registered action
string. There is no execution path here at all, silent or otherwise --
building the actual confirmation dialog and running the action is a UI/
bridge concern (see ui/web/bridge_known_disk.py and
resources/web/spike/profile_automation.js).

Matching is by volume LABEL, not drive letter or mount point -- a letter can
be reassigned to a different disk entirely across reboots/insert order (same
reasoning as engine/disk_reconnect_service.py, which matches by volume
serial number for the same reason; label is used here instead because it's
the identifier a user can actually read/set on the disk itself, useful for
a human picking it out of a settings list).

Persistence follows the same tmp-file + os.replace() pattern as
engine/routing_rules.py: tolerant of a missing/corrupt file, atomic write.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass

import psutil
from PySide6.QtCore import QObject, Signal

from torrent2000.config.paths import get_known_disks_path
from torrent2000.config.settings import Settings
from torrent2000.engine.volume_serial import get_volume_label
from torrent2000.utils.qt_timers import start_periodic_timer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 7_000


@dataclass
class KnownDisk:
    label: str  # Windows volume label, matched case-sensitively as-is
    action: str  # free-form description of what to do -- never executed here, see module docstring


class KnownDiskStore:
    """Persists the label->action associations to disk as JSON."""

    def __init__(self) -> None:
        self._disks: list[KnownDisk] = []
        self._load()

    def list_disks(self) -> list[KnownDisk]:
        return list(self._disks)

    def save_disk(self, disk: KnownDisk) -> None:
        """Adds `disk`, or replaces the existing entry for the same label."""
        for i, existing in enumerate(self._disks):
            if existing.label == disk.label:
                self._disks[i] = disk
                self._save()
                return
        self._disks.append(disk)
        self._save()

    def delete(self, label: str) -> None:
        self._disks = [d for d in self._disks if d.label != label]
        self._save()

    # ------------------------------------------------------------- persistence

    def _save(self) -> None:
        path = get_known_disks_path()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        data = [asdict(d) for d in self._disks]
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def _load(self) -> None:
        path = get_known_disks_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, list):
            return  # malformed top-level shape -- start empty rather than crash on startup
        for entry in data:
            try:
                self._disks.append(KnownDisk(**entry))
            except TypeError:
                continue  # malformed/outdated entry -- skip rather than crash on startup


class KnownDiskService(QObject):
    # (disk_info_json, action) -- disk_info_json is a JSON-encoded
    # {"label": ..., "mountpoint": ...} object, so this stays a plain
    # Signal(str, str) rather than needing a QVariantMap. Purely a request:
    # nothing downstream of this signal runs unless/until the UI builds a
    # confirmation dialog and the user explicitly accepts it.
    diskConfirmationRequested = Signal(str, str)

    def __init__(self, store: KnownDiskStore, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = settings
        # Mount points already seen on a previous tick -- so a disk that was
        # already inserted before the feature was enabled (or before this
        # service even started) doesn't fire the instant it's first checked;
        # only a mount point that *appears* between two ticks counts as a
        # fresh insertion. Tracked every tick regardless of the enabled flag,
        # so toggling the setting on later doesn't retroactively treat
        # already-present disks as "just inserted".
        self._seen_mountpoints: set[str] = set()

        self._timer = start_periodic_timer(self, CHECK_INTERVAL_MS, self.check_now)

    def check_now(self) -> None:
        known: dict[str, str] | None = None
        if self._settings.known_disk_automation_enabled:
            known = {d.label: d.action for d in self._store.list_disks()}

        current_mountpoints: set[str] = set()
        for part in psutil.disk_partitions():
            mountpoint = part.mountpoint
            current_mountpoints.add(mountpoint)
            if mountpoint in self._seen_mountpoints:
                continue  # already tracked -- not a fresh insertion
            if known:
                label = get_volume_label(mountpoint)
                if label and label in known:
                    info = json.dumps({"label": label, "mountpoint": mountpoint})
                    self.diskConfirmationRequested.emit(info, known[label])
        self._seen_mountpoints = current_mountpoints
