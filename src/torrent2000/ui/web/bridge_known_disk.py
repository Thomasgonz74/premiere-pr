"""QWebChannel bridge for KnownDiskService -- lets the Profile tab's
"Automation" group register/list/remove known-disk label->action
associations (live-apply, no Save button, same convention as RssBridge's
feed list), and forwards the service's confirmation-request signal to JS.

This bridge does NOT execute any action and does NOT build the confirmation
dialog -- it only stores associations and relays the request signal. See
known_disk_service.py's module docstring for why, and
resources/web/spike/profile_automation.js for what currently happens with
the forwarded signal.
"""

from PySide6.QtCore import QObject, Signal, Slot

from torrent2000.engine.known_disk_service import KnownDisk, KnownDiskService, KnownDiskStore


class KnownDiskBridge(QObject):
    diskConfirmationRequested = Signal(str, str)  # (disk_info_json, action)

    def __init__(self, store: KnownDiskStore, service: KnownDiskService, parent=None) -> None:
        super().__init__(parent)
        self._store = store
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
