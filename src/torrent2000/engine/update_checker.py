"""Checks GitHub Releases for a newer version of the app.

Uses the same background-QRunnable + stdlib-urllib pattern as
rss_feed_service.py -- no requests dependency, and the GUI thread is never
blocked by the network call.

This is a best-effort, non-critical check: no internet connection, GitHub
being unreachable, or hitting the unauthenticated API's rate limit should
never surface as an error to the user, just a quiet skip (logged, nothing
shown). The only user-visible outcome is the positive case -- a genuinely
newer release exists.

download_verified_installer() is the opt-in next step, only triggered once
the user has already clicked "Download" in MainWindow: GitHub attaches a
"sha256:<hex>" digest to every release asset it hosts, so this re-downloads
the chosen asset, hashes it, and reports success only if the hash matches
that published digest. A mismatch, or an asset with no digest at all, is
treated the same as any other unverifiable download -- installer_verification_failed
fires and the caller falls back to the plain open-the-release-page behavior
that already existed before this. Nothing here ever launches the installer;
that still requires a second, separate explicit confirmation in MainWindow.
"""

import hashlib
import json
import logging
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from torrent2000 import APP_VERSION
from torrent2000.config.settings import ProxySettings, Settings
from torrent2000.engine.url_fetch import FetchError, fetch_url

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/Thomasgonz74/premiere-pr/releases/latest"
USER_AGENT = f"Torrent2000/{APP_VERSION}"
FETCH_TIMEOUT_SECONDS = 10
DOWNLOAD_TIMEOUT_SECONDS = 120  # the installer itself is tens of MB, unlike the small JSON check above
# GitHub's own API should never return anything else for this endpoint's
# html_url -- reject anything else as a malformed/spoofed response rather
# than later opening it in a browser.
EXPECTED_HTML_URL_PREFIX = "https://github.com/"


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


TEMP_INSTALLER_GLOB = "torrent2000_update_*"


def _cleanup_stale_installers() -> None:
    """Best-effort removal of verified-installer copies left behind by
    earlier runs -- e.g. the user picked "later"/closed the dialog instead of
    launching, or the previous copy was still locked by a just-launched
    installer at the time. Runs before every new download so orphans never
    accumulate past one extra run's worth. Failures (permission errors on a
    file still in use) are swallowed; the next run will retry."""
    for stale in Path(tempfile.gettempdir()).glob(TEMP_INSTALLER_GLOB):
        try:
            stale.unlink()
        except OSError:
            pass


def _find_installer_asset(assets: list[dict]) -> dict | None:
    """Prefers an asset whose name contains "Setup" (the full installer,
    e.g. Torrent2000-Setup.exe) over the portable .exe also published on
    every release -- falls back to any .exe if none matches."""
    for asset in assets:
        if "setup" in asset.get("name", "").lower():
            return asset
    for asset in assets:
        if asset.get("name", "").lower().endswith(".exe"):
            return asset
    return None


class _UpdateCheckSignals(QObject):
    succeeded = Signal(str, str, list)  # tag_name, release page html_url, assets
    failed = Signal(str)  # error message, logged only
    install_ready = Signal(str)  # local path to a sha256-verified installer
    verify_failed = Signal(str)  # reason verification/download was skipped


class _CheckUpdateRunnable(QRunnable):
    def __init__(self, signals: _UpdateCheckSignals, proxy: ProxySettings | None = None) -> None:
        super().__init__()
        self._signals = signals
        self._proxy = proxy

    def run(self) -> None:
        try:
            raw = fetch_url(
                GITHUB_API_URL,
                USER_AGENT,
                FETCH_TIMEOUT_SECONDS,
                extra_headers={"Accept": "application/vnd.github+json"},
                proxy=self._proxy,
            )
            data = json.loads(raw)
        except (FetchError, json.JSONDecodeError) as exc:
            self._signals.failed.emit(str(exc))
            return
        tag_name = data.get("tag_name", "")
        html_url = data.get("html_url", "")
        if not tag_name or not html_url or not html_url.startswith(EXPECTED_HTML_URL_PREFIX):
            self._signals.failed.emit("Malformed release response (missing/invalid tag_name/html_url)")
            return
        assets = [
            {
                "name": asset.get("name", ""),
                "browser_download_url": asset.get("browser_download_url", ""),
                "digest": asset.get("digest", ""),
            }
            for asset in data.get("assets", [])
        ]
        self._signals.succeeded.emit(tag_name, html_url, assets)


class _DownloadVerifiedInstallerRunnable(QRunnable):
    """Re-downloads a single release asset and only reports success if its
    SHA-256 matches the digest GitHub published for it -- never launches
    anything itself, just hands a verified local path back to the GUI
    thread."""

    def __init__(self, asset: dict, signals: _UpdateCheckSignals, proxy: ProxySettings | None = None) -> None:
        super().__init__()
        self._asset = asset
        self._signals = signals
        self._proxy = proxy

    def run(self) -> None:
        name = self._asset.get("name", "installer.exe")
        digest = self._asset.get("digest", "")
        if not digest.startswith("sha256:"):
            self._signals.verify_failed.emit(f"No sha256 digest published for {name}")
            return
        expected_hash = digest[len("sha256:") :]

        try:
            data = fetch_url(
                self._asset.get("browser_download_url", ""), USER_AGENT, DOWNLOAD_TIMEOUT_SECONDS, proxy=self._proxy
            )
        except FetchError as exc:
            self._signals.verify_failed.emit(str(exc))
            return

        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != expected_hash:
            self._signals.verify_failed.emit(f"SHA-256 mismatch for {name}")
            return

        _cleanup_stale_installers()
        temp_path = Path(tempfile.gettempdir()) / f"torrent2000_update_{uuid.uuid4().hex}_{name}"
        try:
            temp_path.write_bytes(data)
        except OSError as exc:
            self._signals.verify_failed.emit(str(exc))
            return
        self._signals.install_ready.emit(str(temp_path))


class UpdateChecker(QObject):
    """Call check_now() once (e.g. shortly after startup) to compare the
    latest GitHub release against APP_VERSION. Emits update_available only
    for a genuinely newer, not-already-dismissed version.

    Once update_available has fired, call download_verified_installer() to
    download and SHA-256-verify that release's installer asset in the
    background; the outcome comes back via installer_verified or
    installer_verification_failed."""

    update_available = Signal(str, str)  # latest_version, release_page_url
    installer_verified = Signal(str)  # local path to a SHA-256-verified installer
    installer_verification_failed = Signal(str)  # reason; caller should fall back to opening the release page

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._latest_assets: list[dict] = []
        self._signals = _UpdateCheckSignals()
        self._signals.succeeded.connect(self._on_checked)
        self._signals.failed.connect(self._on_failed)
        self._signals.install_ready.connect(self.installer_verified)
        self._signals.verify_failed.connect(self._on_verify_failed)

    def check_now(self) -> None:
        if not self._settings.check_for_updates:
            return
        QThreadPool.globalInstance().start(_CheckUpdateRunnable(self._signals, proxy=self._settings.proxy))

    def download_verified_installer(self) -> None:
        asset = _find_installer_asset(self._latest_assets)
        if asset is None:
            self._on_verify_failed("No installer asset found in the latest release")
            return
        QThreadPool.globalInstance().start(
            _DownloadVerifiedInstallerRunnable(asset, self._signals, proxy=self._settings.proxy)
        )

    def _on_checked(self, tag_name: str, html_url: str, assets: list) -> None:
        self._latest_assets = assets
        if not is_newer_version(tag_name, APP_VERSION):
            return
        if tag_name == self._settings.dismissed_update_version:
            return
        self.update_available.emit(tag_name, html_url)

    def _on_failed(self, message: str) -> None:
        logger.info("Update check skipped (non-fatal): %s", message)

    def _on_verify_failed(self, message: str) -> None:
        logger.warning("Installer verification skipped, falling back to opening the release page: %s", message)
        self.installer_verification_failed.emit(message)
