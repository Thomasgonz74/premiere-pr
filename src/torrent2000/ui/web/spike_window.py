"""Phase 0 spike host window: a frameless QMainWindow whose entire client
area is one QWebEngineView. Validates the plan's core architecture bet --
QWebChannel bridging to a real SessionManager, window drag/resize via
startSystemMove/startSystemResize, and a real PyInstaller --onedir build --
on a deliberately small surface (title bar + downloads list) before
committing to porting the other ~30 widgets/dialogs.
"""

import json
from ctypes import wintypes

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QMainWindow, QSystemTrayIcon

# Windows message IDs for the live native drag-resize gesture (winuser.h) --
# not exposed as Qt constants, hence the raw ctypes/MSG struct parsing below.
_WM_ENTERSIZEMOVE = 0x0231
_WM_EXITSIZEMOVE = 0x0232

from torrent2000 import APP_NAME
from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.ui.web.bridge_add import AddBridge
from torrent2000.ui.web.bridge_auto_shutdown import AutoShutdownBridge
from torrent2000.ui.web.bridge_create_torrent import CreateTorrentBridge
from torrent2000.ui.web.bridge_downloads import DownloadsBridge
from torrent2000.ui.web.bridge_file_priority import FilePriorityBridge
from torrent2000.ui.web.bridge_known_disk import KnownDiskBridge
from torrent2000.ui.web.bridge_peer_list import PeerListBridge
from torrent2000.ui.web.bridge_profile_advanced import ProfileAdvancedBridge
from torrent2000.ui.web.bridge_profile_automation import ProfileAutomationBridge
from torrent2000.ui.web.bridge_profile_general import ProfileGeneralBridge
from torrent2000.ui.web.bridge_profile_network import ProfileNetworkBridge
from torrent2000.ui.web.bridge_profile_security import ProfileSecurityBridge
from torrent2000.ui.web.bridge_profile_stats import ProfileStatsBridge
from torrent2000.ui.web.bridge_rss import RssBridge
from torrent2000.ui.web.bridge_share import ShareBridge
from torrent2000.ui.web.bridge_speed_graph import SpeedGraphBridge
from torrent2000.ui.web.bridge_storage_sunburst import StorageSunburstBridge
from torrent2000.ui.web.bridge_swarm_constellation import SwarmConstellationBridge
from torrent2000.ui.web.bridge_tracker_editor import TrackerEditorBridge
from torrent2000.ui.web.bridge_update import UpdateBridge
from torrent2000.ui.web.dialog_bridge import DialogBridge
from torrent2000.ui.web.window_bridge import WindowBridge
from torrent2000.utils.resource_path import resource_path

from PySide6.QtCore import Qt


class _ConsoleLoggingPage(QWebEnginePage):
    """Only used when debug=True -- PySide6's virtual-method dispatch for
    QWebEnginePage callbacks requires a genuine Python subclass (confirmed
    this session: monkeypatching the base class's method attribute is
    silently never called), so this can't be a runtime attribute swap."""

    def javaScriptConsoleMessage(self, level, message, line, source) -> None:
        print(f"JS[{level}] {source}:{line} {message}", flush=True)
        super().javaScriptConsoleMessage(level, message, line, source)


class SpikeWindow(QMainWindow):
    def __init__(
        self,
        session_manager: SessionManager,
        settings: Settings,
        share_limit_service: ShareLimitService,
        *,
        stats_service,
        history_service,
        rss_feed_service,
        bandwidth_scheduler,
        disk_space_monitor,
        remote_access_server,
        routing_rule_store,
        settings_profile_store,
        auto_shutdown_service,
        anthem_player,
        update_checker,
        known_disk_store,
        known_disk_service,
        network_profile_store,
        decision_journal_service,
        parent=None,
        debug: bool = False,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        # Real per-pixel window translucency (not an OS region mask): lets
        # rounded corners and any glass-chrome theme (e.g. win7_aero) show
        # the actual desktop behind the window, blurred/tinted by the page's
        # own CSS -- not just a solid fallback color cut to a rounded shape.
        # DWM composites this window's true alpha channel with whatever is
        # really behind it; a mask can only ever hide pixels, never reveal
        # what's underneath.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(980, 640)
        self.setMinimumSize(640, 420)

        # No setCentralWidget() here on purpose: QMainWindow's own layout
        # would auto-resize the view on every single resizeEvent, which is
        # exactly the resize-fluidity problem -- geometry is managed by hand
        # in resizeEvent() below instead, so it can be suppressed during a
        # live native drag-resize (see _begin_resize_freeze).
        self._view = QWebEngineView(self)
        self._view.setAttribute(Qt.WA_TranslucentBackground, True)
        self._view.setGeometry(self.rect())
        if debug:
            # Configure only the page that will actually be used -- calling
            # self._view.page() first would lazily create a default
            # QWebEnginePage just to immediately discard it via setPage().
            page = _ConsoleLoggingPage(self._view)
            page.setBackgroundColor(QColor(0, 0, 0, 0))
            self._view.setPage(page)
        else:
            self._view.page().setBackgroundColor(QColor(0, 0, 0, 0))

        # open_source() needs window.bridge.add to exist, which only happens
        # once the page has actually finished loading (setUrl() below is
        # async) -- a call arriving before that (e.g. a .torrent path passed
        # on the command line at startup) is queued here instead of racing
        # runJavaScript against an unloaded page.
        self._page_loaded = False
        self._pending_open_source: str | None = None
        self._view.page().loadFinished.connect(self._on_page_loaded)

        # Frozen-snapshot overlay for the live-resize fluidity fix: hidden
        # until a native drag-resize gesture starts, then shows a static
        # grab() of the view's last-rendered frame, stretched to track the
        # window's live outline while the OS-driven resize loop runs, so the
        # user never sees Chromium's own reflow lag mid-drag. Sits above the
        # view (raised) only while _is_native_resizing is True.
        self._resize_overlay = QLabel(self)
        self._resize_overlay.setScaledContents(True)
        self._resize_overlay.hide()
        self._is_native_resizing = False

        self._channel = QWebChannel(self)
        self._window_bridge = WindowBridge(self, settings, anthem_player, self)
        self._auto_shutdown_bridge = AutoShutdownBridge(auto_shutdown_service, self)
        self._auto_shutdown_bridge.countdownStarted.connect(self._on_shutdown_countdown_started)
        self._downloads_bridge = DownloadsBridge(session_manager, bandwidth_scheduler, self)
        self._add_bridge = AddBridge(session_manager, settings, routing_rule_store, self)
        self._share_bridge = ShareBridge(session_manager, share_limit_service, settings, self)
        self._dialog_bridge = DialogBridge(self, self)
        self._rss_bridge = RssBridge(session_manager, rss_feed_service, settings, self)
        self._profile_general_bridge = ProfileGeneralBridge(session_manager, settings, self)
        self._profile_general_bridge.volumeChanged.connect(anthem_player.set_volume)
        self._profile_network_bridge = ProfileNetworkBridge(session_manager, settings, remote_access_server, self)
        self._profile_automation_bridge = ProfileAutomationBridge(
            settings, bandwidth_scheduler, disk_space_monitor, decision_journal_service, self
        )
        self._profile_security_bridge = ProfileSecurityBridge(settings, self)
        self._profile_advanced_bridge = ProfileAdvancedBridge(
            session_manager, settings, routing_rule_store, settings_profile_store, network_profile_store, self
        )
        self._profile_stats_bridge = ProfileStatsBridge(stats_service, history_service, self)
        self._file_priority_bridge = FilePriorityBridge(session_manager, self)
        self._peer_list_bridge = PeerListBridge(session_manager, settings, self)
        self._speed_graph_bridge = SpeedGraphBridge(session_manager, self)
        self._swarm_constellation_bridge = SwarmConstellationBridge(session_manager, self)
        self._storage_sunburst_bridge = StorageSunburstBridge(session_manager, self)
        self._create_torrent_bridge = CreateTorrentBridge(self)
        self._tracker_editor_bridge = TrackerEditorBridge(session_manager, self)
        self._update_bridge = UpdateBridge(update_checker, settings, self, self)
        self._known_disk_bridge = KnownDiskBridge(known_disk_store, known_disk_service, session_manager, self)
        self._channel.registerObject("windowBridge", self._window_bridge)
        self._channel.registerObject("autoShutdown", self._auto_shutdown_bridge)
        self._channel.registerObject("downloads", self._downloads_bridge)
        self._channel.registerObject("add", self._add_bridge)
        self._channel.registerObject("share", self._share_bridge)
        self._channel.registerObject("dialogs", self._dialog_bridge)
        self._channel.registerObject("rss", self._rss_bridge)
        self._channel.registerObject("profileGeneral", self._profile_general_bridge)
        self._channel.registerObject("profileNetwork", self._profile_network_bridge)
        self._channel.registerObject("profileAutomation", self._profile_automation_bridge)
        self._channel.registerObject("profileSecurity", self._profile_security_bridge)
        self._channel.registerObject("profileAdvanced", self._profile_advanced_bridge)
        self._channel.registerObject("profileStats", self._profile_stats_bridge)
        self._channel.registerObject("filePriority", self._file_priority_bridge)
        self._channel.registerObject("peerList", self._peer_list_bridge)
        self._channel.registerObject("speedGraph", self._speed_graph_bridge)
        self._channel.registerObject("swarmConstellation", self._swarm_constellation_bridge)
        self._channel.registerObject("storageSunburst", self._storage_sunburst_bridge)
        self._channel.registerObject("createTorrent", self._create_torrent_bridge)
        self._channel.registerObject("trackerEditor", self._tracker_editor_bridge)
        self._channel.registerObject("update", self._update_bridge)
        self._channel.registerObject("knownDisk", self._known_disk_bridge)
        self._view.page().setWebChannel(self._channel)

        index_path = resource_path("resources/web/spike/index.html")
        self._view.setUrl(QUrl.fromLocalFile(str(index_path)))

    def nativeEvent(self, event_type, message):
        # Detects the start/end of a live native drag-resize gesture so the
        # QWebEngineView content can be frozen behind a static snapshot for
        # the duration -- the actual fix for the resize-fluidity debt (see
        # plan: idempotent-gathering-fern.md, "Dette technique actée").
        # Chromium's compositor runs out-of-band from Qt's own resize
        # events and typically trails 1-2 frames behind the OS-driven live
        # window outline during a drag; Electron/CEF apps hide this exact
        # same way (WM_ENTERSIZEMOVE -> freeze, WM_EXITSIZEMOVE -> resume)
        # rather than trying to make Chromium reflow faster, which isn't
        # something this process controls.
        #
        # Overridden here (a per-widget virtual method) rather than via
        # QAbstractNativeEventFilter.installNativeEventFilter() on the whole
        # QApplication -- that global-hook approach was tried first and
        # crashed the process as soon as QWebEngineView started receiving
        # its own native messages (its child processes/surfaces appear to
        # deliver messages through the same "windows_generic_MSG" channel
        # in a shape this address-casting code can't safely assume; a
        # per-widget override only ever sees messages Qt has already
        # resolved as addressed to *this* window, sidestepping that).
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == _WM_ENTERSIZEMOVE:
                self._begin_resize_freeze()
            elif msg.message == _WM_EXITSIZEMOVE:
                self._end_resize_freeze()
        return super().nativeEvent(event_type, message)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._is_native_resizing:
            # Frozen: only the overlay (a cheap pixmap stretch, no Chromium
            # reflow) tracks the window's live outline during the drag.
            self._resize_overlay.setGeometry(self.rect())
        else:
            self._view.setGeometry(self.rect())

    def _begin_resize_freeze(self) -> None:
        if self._is_native_resizing:
            return
        pixmap = self._view.grab()
        if pixmap.isNull():
            return  # nothing rendered yet (e.g. gesture started before first paint) -- skip freezing
        self._resize_overlay.setPixmap(pixmap)
        self._resize_overlay.setGeometry(self._view.geometry())
        self._resize_overlay.show()
        self._resize_overlay.raise_()
        self._is_native_resizing = True

    def _end_resize_freeze(self) -> None:
        if not self._is_native_resizing:
            return
        self._is_native_resizing = False
        self._view.setGeometry(self.rect())
        # A brief delay before revealing the live view again: Chromium needs
        # at least one paint cycle to catch up to the final size, and
        # dropping the overlay immediately would flash the same 1-2 frames
        # of stale/mid-reflow content this whole mechanism exists to hide.
        QTimer.singleShot(80, self._resize_overlay.hide)

    def _on_page_loaded(self, ok: bool) -> None:
        self._page_loaded = True
        if ok and self._pending_open_source is not None:
            source, self._pending_open_source = self._pending_open_source, None
            self._run_open_source(source)

    def open_source(self, source: str) -> None:
        """Called with a .torrent path or magnet: URI when the app is
        launched via the installer's file/protocol association (double-
        clicking a .torrent file, or clicking a magnet link in a browser) --
        mirrors native MainWindow.open_source exactly, just routed through
        the Add page's already-exposed bridge slots via runJavaScript
        instead of direct Python calls."""
        if not self._page_loaded:
            self._pending_open_source = source
            return
        self._run_open_source(source)

    def _run_open_source(self, source: str) -> None:
        escaped = json.dumps(source)
        if source.lower().startswith("magnet:"):
            js = f"switchToTab('add'); window.bridge.add.analyzeMagnet({escaped});"
        else:
            js = f"switchToTab('add'); window.bridge.add.selectTorrentFile({escaped});"
        self._view.page().runJavaScript(js)

    def _on_shutdown_countdown_started(self, delay_seconds: int) -> None:
        # The signal only carries the delay (matches AutoShutdownService's
        # own Signal(int)) -- the action ("shutdown"/"hibernate") is read
        # fresh from settings here, same as the native dialog receives it
        # as a separate constructor argument rather than through the signal.
        action = self._settings.auto_shutdown_action
        self._view.page().runJavaScript(f"showAutoShutdownCountdown({delay_seconds}, {action!r})")

    def closeEvent(self, event) -> None:
        # Mirrors MainWindow.closeEvent: closing the window minimizes to tray
        # instead of quitting, same as native -- actual shutdown happens via
        # app.aboutToQuit (run_web_spike.py's _shutdown), triggered by the
        # tray menu's "Quitter" action, not by this event.
        if self._settings.minimize_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)
