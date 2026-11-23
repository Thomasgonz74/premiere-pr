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
from torrent2000.engine.decision_journal import _LIMIT_REASON_KEYS
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.url_fetch import FetchCancelled, FetchError, fetch_url
from torrent2000.i18n.translator import tr

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
                self._url,
                USER_AGENT,
                TIMEOUT_SECONDS,
                # Not urllib's default form encoding: a generic endpoint would
                # split the message at "&" and turn "+" into a space.
                extra_headers={"Content-Type": "text/plain; charset=utf-8"},
                data=self._message.encode("utf-8"),
                proxy=self._proxy,
            )
        except FetchCancelled:
            return  # quitting
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
        # Deliberately NOT de-duplicated per error episode (unlike the tray
        # toasts in ui/notifications.py): the user declined that behaviour
        # change on 2026-09-27, so every tracker/file error is posted.
        session_manager.torrent_finished.connect(self._on_torrent_finished)
        session_manager.tracker_error.connect(self._on_tracker_error)
        session_manager.file_error.connect(self._on_file_error)
        share_limit_service.limit_reached.connect(self._on_limit_reached)

    def _send(self, title_key: str, body: str) -> None:
        """The tray toast's title and text (ui/notifications.py), on one
        line, in the language of the interface."""
        if not self._settings.webhook_enabled or not self._settings.webhook_url:
            return
        message = f"{tr(title_key)} -- {body}"
        runnable = _WebhookPostRunnable(self._settings.webhook_url, message, proxy=self._settings.proxy)
        QThreadPool.globalInstance().start(runnable)

    def _record_name(self, info_hash: str) -> str:
        record = self._session_manager.get_record(info_hash)
        return record.name if record is not None else info_hash[:12]

    def _on_torrent_finished(self, info_hash: str) -> None:
        self._send("notifications.download_finished_title", self._record_name(info_hash))

    def _on_tracker_error(self, info_hash: str, message: str) -> None:
        name = self._record_name(info_hash)
        self._send("notifications.tracker_error_title", tr("notifications.tracker_error_message", name=name, message=message))

    def _on_file_error(self, info_hash: str, message: str) -> None:
        name = self._record_name(info_hash)
        self._send("notifications.file_error_title", tr("notifications.file_error_message", name=name, message=message))

    def _on_limit_reached(self, info_hash: str, reason: str) -> None:
        # The journal's wording for ShareLimitService's code: unlike the
        # toast's, it names the ratio limit too.
        label = tr(_LIMIT_REASON_KEYS.get(reason, "notifications.limit_reason_generic"))
        self._send(
            "notifications.share_paused_title",
            tr("notifications.share_paused_message", name=self._record_name(info_hash), reason=label),
        )
