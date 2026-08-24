"""Native Windows notifications for download/share completion, via a
QSystemTrayIcon (the standard Qt way to surface OS toast-style messages)."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from torrent2000 import APP_NAME
from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.i18n.translator import tr
from torrent2000.utils.resource_path import resource_path

_LIMIT_REASON_KEYS = {"time": "notifications.limit_reason_time", "data": "notifications.limit_reason_data"}
_MESSAGE_DURATION_MS = 6000

_TRAY_ACTIVATION_REASONS = (QSystemTrayIcon.ActivationReason.DoubleClick, QSystemTrayIcon.ActivationReason.Trigger)


class NotificationService(QObject):
    show_requested = Signal()
    quit_requested = Signal()

    def __init__(
        self,
        session_manager: SessionManager,
        share_limit_service: ShareLimitService,
        settings: Settings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._tray_icon = None
        self._notified_tracker_errors: set[str] = set()
        self._notified_file_errors: set[str] = set()

        if QSystemTrayIcon.isSystemTrayAvailable():
            icon_path = resource_path("assets/icon.ico")
            icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
            self._tray_icon = QSystemTrayIcon(icon, parent)
            self._tray_icon.setToolTip(APP_NAME)
            menu = QMenu()
            show_action = menu.addAction(tr("notifications.tray_show_action"))
            show_action.triggered.connect(self.show_requested)
            quit_action = menu.addAction(tr("notifications.tray_quit_action"))
            quit_action.triggered.connect(self.quit_requested)
            self._tray_icon.setContextMenu(menu)
            self._tray_icon.activated.connect(self._on_tray_activated)
            self._tray_icon.show()

        session_manager.torrent_finished.connect(self._on_torrent_finished)
        share_limit_service.limit_reached.connect(self._on_limit_reached)
        session_manager.tracker_error.connect(self._on_tracker_error)
        session_manager.file_error.connect(self._on_file_error)
        session_manager.torrent_removed.connect(self._on_torrent_removed)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in _TRAY_ACTIVATION_REASONS:
            self.show_requested.emit()

    def _notify(self, title: str, message: str) -> None:
        if self._tray_icon is not None and self._settings.notifications_enabled:
            self._tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, _MESSAGE_DURATION_MS)

    def _on_torrent_finished(self, info_hash: str) -> None:
        record = self._session_manager.get_record(info_hash)
        name = record.name if record is not None else info_hash[:12]
        self._notify(tr("notifications.download_finished_title"), name)

    def _on_limit_reached(self, info_hash: str, reason: str) -> None:
        record = self._session_manager.get_record(info_hash)
        name = record.name if record is not None else info_hash[:12]
        label = tr(_LIMIT_REASON_KEYS.get(reason, "notifications.limit_reason_generic"))
        self._notify(tr("notifications.share_paused_title"), tr("notifications.share_paused_message", name=name, reason=label))

    def _on_tracker_error(self, info_hash: str, message: str) -> None:
        # A flaky tracker can re-fire this alert repeatedly for the same
        # torrent; only surface one toast per "episode" (until the torrent is
        # removed) instead of spamming. SessionManager doesn't currently
        # expose a tracker-recovered event, so removal is the only reset we
        # have available here.
        if info_hash in self._notified_tracker_errors:
            return
        self._notified_tracker_errors.add(info_hash)
        record = self._session_manager.get_record(info_hash)
        name = record.name if record is not None else info_hash[:12]
        self._notify(
            tr("notifications.tracker_error_title"),
            tr("notifications.tracker_error_message", name=name, message=message),
        )

    def _on_file_error(self, info_hash: str, message: str) -> None:
        # Same "one toast per episode" suppression as tracker errors, and the
        # same reason: no file-error-recovered event exists to reset on, so
        # removal is the only reset point available.
        if info_hash in self._notified_file_errors:
            return
        self._notified_file_errors.add(info_hash)
        record = self._session_manager.get_record(info_hash)
        name = record.name if record is not None else info_hash[:12]
        self._notify(
            tr("notifications.file_error_title"),
            tr("notifications.file_error_message", name=name, message=message),
        )

    def _on_torrent_removed(self, info_hash: str) -> None:
        self._notified_tracker_errors.discard(info_hash)
        self._notified_file_errors.discard(info_hash)
