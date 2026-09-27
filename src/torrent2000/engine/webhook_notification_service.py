"""Webhook/ntfy notifications (catalogue idea) -- POSTs a short plain-text
message to a user-configured URL for the same events ui/notifications.py
already shows as a system tray toast, for users who close their PC or don't
want to rely on engine/remote_server.py (LAN-only).

OFF BY DEFAULT (Settings.webhook_enabled/webhook_url). Works as-is with
ntfy.sh's simplest usage (POST the message body to https://ntfy.sh/<topic>);
any other webhook endpoint that accepts a plain-text POST body works too.

The POST runs on a QThreadPool worker (same pattern as
rss_feed_service.py's runnables) so a slow/dead webhook endpoint never
blocks the GUI thread.
"""

import logging

from PySide6.QtCore import QObject, QRunnable, QThreadPool

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.url_fetch import FetchError, fetch_url

logger = logging.getLogger(__name__)

USER_AGENT = "Torrent2000-Webhook/1"
TIMEOUT_SECONDS = 10


class _WebhookPostRunnable(QRunnable):
    def __init__(self, url: str, message: str, proxy=None) -> None:
        super().__init__()
        self._url = url
        self._message = message
        self._proxy = proxy

    def run(self) -> None:
        try:
            fetch_url(
                self._url, USER_AGENT, TIMEOUT_SECONDS, data=self._message.encode("utf-8"), proxy=self._proxy
            )
        except FetchError:
            logger.exception("Webhook notification POST failed")


class WebhookNotificationService(QObject):
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
        session_manager.torrent_finished.connect(self._on_torrent_finished)
        session_manager.tracker_error.connect(self._on_tracker_error)
        session_manager.file_error.connect(self._on_file_error)
        share_limit_service.limit_reached.connect(self._on_limit_reached)

    def _send(self, message: str) -> None:
        if not self._settings.webhook_enabled or not self._settings.webhook_url:
            return
        runnable = _WebhookPostRunnable(self._settings.webhook_url, message, proxy=self._settings.proxy)
        QThreadPool.globalInstance().start(runnable)

    def _record_name(self, info_hash: str) -> str:
        record = self._session_manager.get_record(info_hash)
        return record.name if record is not None else info_hash[:12]

    def _on_torrent_finished(self, info_hash: str) -> None:
        self._send(f"Téléchargement terminé : {self._record_name(info_hash)}")

    def _on_tracker_error(self, info_hash: str, message: str) -> None:
        self._send(f"Erreur de tracker ({self._record_name(info_hash)}) : {message}")

    def _on_file_error(self, info_hash: str, message: str) -> None:
        self._send(f"Erreur disque/fichier ({self._record_name(info_hash)}) : {message}")

    def _on_limit_reached(self, info_hash: str, reason: str) -> None:
        self._send(f"Partage en pause ({self._record_name(info_hash)}) : limite {reason} atteinte")
