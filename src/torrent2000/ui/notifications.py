"""Native Windows notifications for download/share completion, via a
QSystemTrayIcon (the standard Qt way to surface OS toast-style messages)."""

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon

from torrent2000 import APP_NAME
from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.utils.resource_path import resource_path

_LIMIT_REASON_LABELS = {"time": "limite de temps atteinte", "data": "limite de données atteinte"}
_MESSAGE_DURATION_MS = 6000


class NotificationService:
    def __init__(
        self,
        session_manager: SessionManager,
        share_limit_service: ShareLimitService,
        settings: Settings,
        parent=None,
    ) -> None:
        self._session_manager = session_manager
        self._settings = settings
        self._tray_icon = None

        if QSystemTrayIcon.isSystemTrayAvailable():
            icon_path = resource_path("assets/icon.ico")
            icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
            self._tray_icon = QSystemTrayIcon(icon, parent)
            self._tray_icon.setToolTip(APP_NAME)
            self._tray_icon.show()

        session_manager.torrent_finished.connect(self._on_torrent_finished)
        share_limit_service.limit_reached.connect(self._on_limit_reached)

    def _notify(self, title: str, message: str) -> None:
        if self._tray_icon is not None and self._settings.notifications_enabled:
            self._tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, _MESSAGE_DURATION_MS)

    def _on_torrent_finished(self, info_hash: str) -> None:
        record = self._session_manager.get_record(info_hash)
        name = record.name if record is not None else info_hash[:12]
        self._notify("Téléchargement terminé", name)

    def _on_limit_reached(self, info_hash: str, reason: str) -> None:
        record = self._session_manager.get_record(info_hash)
        name = record.name if record is not None else info_hash[:12]
        label = _LIMIT_REASON_LABELS.get(reason, "limite atteinte")
        self._notify("Partage mis en pause", f"{name} -- {label}")
