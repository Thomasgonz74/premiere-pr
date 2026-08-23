"""QWebChannel bridge for UpdateChecker -- forwards updateAvailable/
installerVerified to JS and exposes the actions the native two-step
download/verify dialogs used to trigger directly, same forwarding pattern as
AutoShutdownBridge/RssBridge. installer_verification_failed has no dialog
even natively (MainWindow just opens the release page and logs a warning),
so it's handled here in Python only, not forwarded to JS.
"""

import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from torrent2000.config.settings import Settings
from torrent2000.engine.update_checker import UpdateChecker


class UpdateBridge(QObject):
    updateAvailable = Signal(str, str)  # version, release_url
    installerVerified = Signal(str)  # local path to a SHA-256-verified installer

    def __init__(self, update_checker: UpdateChecker, settings: Settings, window, parent=None) -> None:
        super().__init__(parent)
        self._update_checker = update_checker
        self._settings = settings
        self._window = window
        self._pending_release_url = ""
        update_checker.update_available.connect(self._on_update_available)
        update_checker.installer_verified.connect(self.installerVerified.emit)
        update_checker.installer_verification_failed.connect(self._on_verification_failed)

    def _on_update_available(self, version: str, release_url: str) -> None:
        self._pending_release_url = release_url
        self.updateAvailable.emit(version, release_url)

    def _on_verification_failed(self, reason: str) -> None:
        if self._pending_release_url:
            QDesktopServices.openUrl(QUrl(self._pending_release_url))

    @Slot()
    def downloadInstaller(self) -> None:
        self._update_checker.download_verified_installer()

    @Slot(str)
    def dismissUpdate(self, version: str) -> None:
        self._settings.dismissed_update_version = version
        self._settings.save()

    @Slot(str)
    def launchInstaller(self, local_path: str) -> None:
        subprocess.Popen([local_path])
        # Torrent2000.exe stays locked by Windows while this process runs,
        # and the installer needs to overwrite it -- close() (not a raw
        # exit) so the normal teardown (stats/session flush) still runs
        # before the file lock is freed, same reasoning as native.
        self._window.close()

    @Slot(str)
    def discardInstaller(self, local_path: str) -> None:
        try:
            Path(local_path).unlink()
        except OSError:
            pass
