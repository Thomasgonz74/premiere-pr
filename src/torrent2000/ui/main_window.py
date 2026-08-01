from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QPainterPath, QRegion
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QSizeGrip, QTabWidget, QVBoxLayout, QWidget

from torrent2000 import APP_NAME
from torrent2000.config.settings import Settings
from torrent2000.engine.auto_shutdown_service import AutoShutdownService
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.service import StatsService
from torrent2000.ui.tabs.add_tab import AddTorrentTab
from torrent2000.ui.tabs.downloads_tab import DownloadsTab
from torrent2000.ui.tabs.profile_tab import ProfileTab
from torrent2000.ui.tabs.rss_tab import RssTab
from torrent2000.ui.tabs.share_tab import ShareTab
from torrent2000.ui.theme.theme_manager import apply_theme, title_bar_style_for
from torrent2000.ui.widgets.app_title_bar import AppTitleBar
from torrent2000.ui.widgets.shutdown_countdown_dialog import ShutdownCountdownDialog


class MainWindow(QMainWindow):
    def __init__(
        self,
        session_manager: SessionManager,
        stats_service: StatsService,
        share_limit_service: ShareLimitService,
        bandwidth_scheduler: BandwidthScheduler,
        history_service: HistoryService,
        settings: Settings,
        rss_feed_service: RssFeedService,
        disk_space_monitor: DiskSpaceMonitor,
        auto_shutdown_service: AutoShutdownService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._stats_service = stats_service
        self._share_limit_service = share_limit_service
        self._bandwidth_scheduler = bandwidth_scheduler
        self._history_service = history_service
        self._settings = settings
        self._auto_shutdown_service = auto_shutdown_service
        self._shutdown_dialog = None

        self.setWindowTitle(APP_NAME)
        # The native Windows title bar can't be restyled to match any of
        # these themes (QSS doesn't reach OS-owned window chrome), so the
        # window runs frameless and AppTitleBar below stands in for it.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.resize(980, 640)

        central = QWidget(self)
        central.setObjectName("centralWidget")
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._title_bar = AppTitleBar(APP_NAME, title_bar_style_for(settings.theme), central)
        outer_layout.addWidget(self._title_bar)

        tabs = QTabWidget(central)
        tabs.setObjectName("mainTabs")
        self._add_tab = AddTorrentTab(session_manager, settings)
        tabs.addTab(self._add_tab, "Ajout / Analyse")
        self._downloads_tab_index = tabs.count()
        tabs.addTab(DownloadsTab(session_manager), "Téléchargements")
        tabs.addTab(ShareTab(session_manager, share_limit_service, settings), "Partage")
        tabs.addTab(RssTab(session_manager, rss_feed_service, settings), "RSS")
        self._profile_tab = ProfileTab(
            session_manager, stats_service, bandwidth_scheduler, history_service, settings, disk_space_monitor
        )
        self._profile_tab.theme_changed.connect(self.set_theme)
        tabs.addTab(self._profile_tab, "Profil")
        outer_layout.addWidget(tabs, 1)
        self._tabs = tabs

        self._add_tab.torrent_started.connect(self._on_torrent_started)
        auto_shutdown_service.shutdown_countdown_started.connect(self._on_shutdown_countdown_started)

        # Frameless windows lose the OS's edge-resize handles; a QSizeGrip
        # in the corner is the low-risk way to get drag-to-resize back
        # without hooking native WM_NCHITTEST edge detection.
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 2, 2)
        grip_row.addStretch(1)
        self._size_grip = QSizeGrip(central)
        grip_row.addWidget(self._size_grip, 0, Qt.AlignBottom | Qt.AlignRight)
        outer_layout.addLayout(grip_row)

        self.setCentralWidget(central)

        self._corner_radius = 0
        self._apply_window_style(settings.theme)

    def _on_torrent_started(self) -> None:
        # Switching to the Downloads tab right after starting a download is
        # more intuitive than leaving the user on the Add tab wondering if
        # anything happened.
        self._tabs.setCurrentIndex(self._downloads_tab_index)

    def _on_shutdown_countdown_started(self, delay_seconds: int) -> None:
        if self._shutdown_dialog is not None:
            return  # a countdown is already showing
        dialog = ShutdownCountdownDialog(delay_seconds, action=self._settings.auto_shutdown_action, parent=self)
        dialog.cancelled.connect(self._auto_shutdown_service.cancel_shutdown)
        dialog.finished.connect(self._on_shutdown_dialog_finished)
        self._shutdown_dialog = dialog
        dialog.show()

    def _on_shutdown_dialog_finished(self) -> None:
        self._shutdown_dialog = None

    def set_theme(self, theme_id: str) -> None:
        app = QGuiApplication.instance()
        if app is not None:
            apply_theme(app, theme_id)
        self._apply_window_style(theme_id)

    def _apply_window_style(self, theme_id: str) -> None:
        style = title_bar_style_for(theme_id)
        self._title_bar.apply_style(style)
        self._corner_radius = style.window_corner_radius
        self._update_corner_mask()

    def _update_corner_mask(self) -> None:
        if self._corner_radius <= 0 or self.isMaximized():
            self.clearMask()
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self._corner_radius, self._corner_radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_corner_mask()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            self._title_bar.refresh_maximize_glyph()
            self._update_corner_mask()

    def closeEvent(self, event) -> None:
        self._stats_service.shutdown()
        self._session_manager.shutdown()
        super().closeEvent(event)
