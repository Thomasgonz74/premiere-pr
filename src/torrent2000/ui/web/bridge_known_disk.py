"""QWebChannel bridge for KnownDiskService -- lets the Profile tab's
"Automation" group register/list/remove known-disk label->action
associations (live-apply, no Save button, same convention as RssBridge's
feed list), and forwards the service's confirmation-request signal to JS.

This bridge does NOT execute anything on its own and does NOT build the
confirmation dialog -- it only stores associations, relays the request
signal, and exposes an explicit preview/execute pair that only ever runs
once the user has confirmed in the UI. See known_disk_service.py's module
docstring for the "never automatic" invariant this must preserve, and
resources/web/spike/profile_automation.js for the confirmation dialog.

Semantics (see profile_automation.js's diskConfirmationRequested handler):
`action` is a torrent CATEGORY name. previewCategoryMove()/executeCategoryMove()
match SessionManager records whose category equals `action` case-insensitively
(after trimming), and move them under "<mountpoint>/<action>".
"""

import os

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.engine.known_disk_service import KnownDisk, KnownDiskService, KnownDiskStore
from torrent2000.engine.session_manager import SessionManager


def _matching_records(session_manager: SessionManager, category: str) -> list:
    wanted = category.strip().casefold()
    return [r for r in session_manager.all_records() if r.category.strip().casefold() == wanted]


class KnownDiskBridge(QObject):
    diskConfirmationRequested = Signal(str, str)  # (disk_info_json, action)

    def __init__(
        self, store: KnownDiskStore, service: KnownDiskService, session_manager: SessionManager, parent=None
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._session_manager = session_manager
        service.diskConfirmationRequested.connect(self.diskConfirmationRequested.emit)

    @Slot(result="QVariantList")
    def listDisks(self) -> list[dict]:
        return [{"label": d.label, "action": d.action} for d in self._store.list_disks()]

    @Slot(str, str, result="QVariantMap")
    def saveDisk(self, label: str, action: str) -> dict:
        label = (label or "").strip()
        if not label:
            return {"ok": False, "error": "Le label du disque est requis."}
        self._store.save_disk(KnownDisk(label=label, action=(action or "").strip()))
        return {"ok": True}

    @Slot(str)
    def deleteDisk(self, label: str) -> None:
        self._store.delete(label)

    @Slot(str, result="QVariantMap")
    def previewCategoryMove(self, category: str) -> dict:
        """Read-only impact preview shown BEFORE any confirmation button is
        even enabled -- never moves anything."""
        records = _matching_records(self._session_manager, category)
        total_size = sum(r.total_size for r in records)
        return {"count": len(records), "totalSize": total_size}

    @Slot(str, str, result="QVariantMap")
    def executeCategoryMove(self, category: str, mountpoint: str) -> dict:
        """Only ever called after the user clicks "Confirmer et déplacer" in
        the UI (see profile_automation.js) -- moves every torrent whose
        category matches `category` under "<mountpoint>/<category>" via
        SessionManager.move_storage. Defensive: one torrent failing to move
        must not stop the rest."""
        target_dir = os.path.join(mountpoint, category.strip())
        moved = 0
        errors: list[str] = []
        for record in _matching_records(self._session_manager, category):
            try:
                self._session_manager.move_storage(record.info_hash, target_dir)
                moved += 1
            except Exception as exc:  # noqa: BLE001 -- one bad handle must not abort the batch
                errors.append(f"{record.name or record.info_hash}: {exc}")
        return {"moved": moved, "errors": errors}
