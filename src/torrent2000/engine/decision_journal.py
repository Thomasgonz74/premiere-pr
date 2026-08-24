"""Journal des décisions automatiques (catalogue "idees non implementees",
cluster Organisation & planification) -- a human-readable history of actions
taken WITHOUT user interaction by the app's own automation services, as
opposed to anything the user does by hand.

Purely reactive (no QTimer of its own): subscribes to signals that ALREADY
exist on other services and appends one JSONL line per event. This is NOT a
new automation channel -- it only ever listens, it never calls back into any
service or acts on anything itself.

Grepped `Signal(` across every automation service in this catalogue on
2026-08-24 to see exactly what's actually connectable today:

  connected:
    - SessionManager.file_error(info_hash, message) -- a disk/file I/O error
      auto-paused a torrent (SessionManager._on_file_error; the pause itself
      is unconditional, not gated by any Settings flag).
    - KnownDiskService.diskConfirmationRequested(info_json, action) -- a
      registered disk was detected and its associated action proposed to the
      user. The action itself is NEVER auto-executed (see
      known_disk_service.py's own docstring) -- journaled anyway as the
      automatic *detection* decision, not as a completed action.
    - DiskSpaceMonitor.low_space_warning(save_path, message) -- free space at
      an active download's save path dropped below the configured threshold.

  NOT connected -- these have no Signal at all today, so there is nothing to
  subscribe to without adding one first (out of scope here):
    - battery_pause_service.py (BatteryPauseService)
    - watch_folder_service.py (WatchFolderService)
    - memory_pressure_governor.py (MemoryPressureGovernor)
    - idle_activity_service.py (IdleActivityService)
    - network_profile_switcher.py (NetworkProfileSwitcherService)

Persistence mirrors config/settings_history.py: append-only JSONL beside
config.json (see config/paths.py's get_decision_journal_path), capped at
_MAX_ENTRIES lines, tolerant of a missing/corrupt file, best-effort (never
raises into a signal handler).
"""

import json
import logging
from datetime import datetime

from PySide6.QtCore import QObject

from torrent2000.config.paths import get_decision_journal_path

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 200  # ponytail: flat line cap like settings_history.py, revisit if too short


def _append(text: str) -> None:
    entry = {"timestamp": datetime.now().isoformat(timespec="seconds"), "text": text}
    path = get_decision_journal_path()
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("Decision journal: failed to append entry")
        return
    _trim()


def _trim() -> None:
    path = get_decision_journal_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= _MAX_ENTRIES:
        return
    try:
        path.write_text("\n".join(lines[-_MAX_ENTRIES:]) + "\n", encoding="utf-8")
    except OSError:
        return


def read_recent_entries(limit: int = 100) -> list[dict]:
    """Returns up to `limit` journal entries, most recent first. Malformed
    lines (e.g. a truncated write) are skipped rather than failing the whole
    read -- mirrors settings_history.read_settings_history."""
    path = get_decision_journal_path()
    if not path.exists():
        return []
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    entries.reverse()
    return entries[:limit]


class DecisionJournalService(QObject):
    """Wires up to the three signals documented above and journals one French
    line per event. No state of its own beyond the Qt connections -- the
    JSONL file is the only state."""

    def __init__(self, session_manager, known_disk_service, disk_space_monitor, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        session_manager.file_error.connect(self._on_file_error)
        known_disk_service.diskConfirmationRequested.connect(self._on_disk_confirmation_requested)
        disk_space_monitor.low_space_warning.connect(self._on_low_space_warning)

    @staticmethod
    def recent_entries(limit: int = 100) -> list[dict]:
        return read_recent_entries(limit)

    def _on_file_error(self, info_hash: str, message: str) -> None:
        # Same get_record-or-fallback-to-hash convention as
        # ui/notifications.py's own _on_file_error.
        record = self._session_manager.get_record(info_hash)
        name = record.name if record is not None else info_hash[:12]
        _append(f"Téléchargement « {name} » mis en pause automatiquement (erreur disque/fichier : {message}).")

    def _on_disk_confirmation_requested(self, info_json: str, action: str) -> None:
        try:
            info = json.loads(info_json)
        except json.JSONDecodeError:
            info = {}
        label = info.get("label", "?")
        _append(f"Disque connu « {label} » détecté -- action proposée (confirmation requise) : {action}.")

    def _on_low_space_warning(self, save_path: str, message: str) -> None:
        _append(f"Espace disque faible détecté pour « {save_path} ».")
