"""Checks GitHub Releases for a newer version of the app.

Uses the same background-QRunnable + stdlib-urllib pattern as
rss_feed_service.py -- no requests dependency, and the GUI thread is never
blocked by the network call.

This is a best-effort, non-critical check: no internet connection, GitHub
being unreachable, or hitting the unauthenticated API's rate limit should
never surface as an error to the user, just a quiet skip (logged, nothing
shown). The only user-visible outcome is the positive case -- a genuinely
newer release exists.
"""

import json
import logging
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from torrent2000 import APP_VERSION
from torrent2000.config.settings import Settings

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/Thomasgonz74/premiere-pr/releases/latest"
USER_AGENT = f"Torrent2000/{APP_VERSION}"
FETCH_TIMEOUT_SECONDS = 10


def parse_version(version: str) -> tuple[int, ...]:
    """"v1.2.0" / "1.2.0" -> (1, 2, 0). Tolerant of a leading "v" and of a
    non-numeric suffix on any part (e.g. a "1.2.0-beta" pre-release tag) by
    taking only that part's leading digits -- not full semver/PEP 440
    parsing, but enough for this app's plain numeric version tags."""
    version = version.lstrip("vV")
    parts = []
    for part in version.split("."):
        digits = ""
        for ch in part:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer_version(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


class _UpdateCheckSignals(QObject):
    succeeded = Signal(str, str)  # tag_name, release page html_url
    failed = Signal(str)  # error message, logged only


class _CheckUpdateRunnable(QRunnable):
    def __init__(self, signals: _UpdateCheckSignals) -> None:
        super().__init__()
        self._signals = signals

    def run(self) -> None:
        request = urllib.request.Request(
            GITHUB_API_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read())
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            self._signals.failed.emit(str(exc))
            return
        tag_name = data.get("tag_name", "")
        html_url = data.get("html_url", "")
        if not tag_name or not html_url:
            self._signals.failed.emit("Malformed release response (missing tag_name/html_url)")
            return
        self._signals.succeeded.emit(tag_name, html_url)


class UpdateChecker(QObject):
    """Call check_now() once (e.g. shortly after startup) to compare the
    latest GitHub release against APP_VERSION. Emits update_available only
    for a genuinely newer, not-already-dismissed version."""

    update_available = Signal(str, str)  # latest_version, release_page_url

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._signals = _UpdateCheckSignals()
        self._signals.succeeded.connect(self._on_checked)
        self._signals.failed.connect(self._on_failed)

    def check_now(self) -> None:
        if not self._settings.check_for_updates:
            return
        QThreadPool.globalInstance().start(_CheckUpdateRunnable(self._signals))

    def _on_checked(self, tag_name: str, html_url: str) -> None:
        if not is_newer_version(tag_name, APP_VERSION):
            return
        if tag_name == self._settings.dismissed_update_version:
            return
        self.update_available.emit(tag_name, html_url)

    def _on_failed(self, message: str) -> None:
        logger.info("Update check skipped (non-fatal): %s", message)
