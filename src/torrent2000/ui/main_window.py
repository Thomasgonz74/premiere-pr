from PySide6.QtCore import QEvent, QRect, QRectF, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QPainterPath, QRegion
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QSizeGrip, QTabWidget, QVBoxLayout, QWidget

RESIZE_MARGIN = 5  # px band around the frameless window's edge that grabs for resize
MIN_WINDOW_SIZE = (640, 420)

_CURSOR_FOR_EDGE = {
    "left": Qt.SizeHorCursor,
    "right": Qt.SizeHorCursor,
    "top": Qt.SizeVerCursor,
    "bottom": Qt.SizeVerCursor,
    "top_left": Qt.SizeFDiagCursor,
    "bottom_right": Qt.SizeFDiagCursor,
    "top_right": Qt.SizeBDiagCursor,
    "bottom_left": Qt.SizeBDiagCursor,
}

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
        # Frameless also means the OS's own edge-resize handling is gone --
        # see the eventFilter-based resize implementation below.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(*MIN_WINDOW_SIZE)
        self.resize(980, 640)

        self._resize_edge = None
        self._resize_start_geometry = None
        self._resize_start_pos = None

        central = QWidget(self)
        central.setObjectName("centralWidget")
        central.setMouseTracking(True)
        central.installEventFilter(self)
        self._central = central
        outer_layout = QVBoxLayout(central)
        # A thin margin, left deliberately free of any child widget, is what
        # lets central (and this eventFilter) actually receive mouse events
        # near the window's edges -- if the title bar/tabs filled the window
        # right to its border, they would be the widgets under the cursor
        # there instead, and this window would never see the event.
        outer_layout.setContentsMargins(RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN)
        outer_layout.setSpacing(0)

        self._title_bar = AppTitleBar(APP_NAME, title_bar_style_for(settings.theme, settings.appearance_mode), central)
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
        session_manager.download_blocked_by_theme.connect(self._on_download_blocked_by_theme)
        session_manager.theme_downloads_paused.connect(self._on_theme_downloads_paused)

        # A visible QSizeGrip reinforces the bottom-right corner as a resize
        # handle (the eventFilter below already lets you drag from any edge
        # or corner of the window, but a corner grip is a more discoverable
        # affordance for the same gesture).
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 2, 2)
        grip_row.addStretch(1)
        self._size_grip = QSizeGrip(central)
        grip_row.addWidget(self._size_grip, 0, Qt.AlignBottom | Qt.AlignRight)
        outer_layout.addLayout(grip_row)

        self.setCentralWidget(central)

        self._corner_radius = 0
        self._apply_window_style(settings.theme, settings.appearance_mode)

    # -------------------------------------------------------- edge resize

    def _edge_at(self, pos) -> str | None:
        w, h = self._central.width(), self._central.height()
        m = RESIZE_MARGIN
        left, right = pos.x() <= m, pos.x() >= w - m
        top, bottom = pos.y() <= m, pos.y() >= h - m
        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return None

    def _perform_resize(self, global_pos) -> None:
        delta = global_pos - self._resize_start_pos
        geo = QRect(self._resize_start_geometry)
        edge = self._resize_edge
        min_w, min_h = MIN_WINDOW_SIZE

        if "left" in edge:
            new_left = geo.left() + delta.x()
            if geo.right() - new_left + 1 >= min_w:
                geo.setLeft(new_left)
        if "right" in edge:
            geo.setWidth(max(min_w, geo.width() + delta.x()))
        if "top" in edge:
            new_top = geo.top() + delta.y()
            if geo.bottom() - new_top + 1 >= min_h:
                geo.setTop(new_top)
        if "bottom" in edge:
            geo.setHeight(max(min_h, geo.height() + delta.y()))

        self.setGeometry(geo)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._central and not self.isMaximized():
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove:
                if self._resize_edge is not None and (event.buttons() & Qt.LeftButton):
                    self._perform_resize(event.globalPosition().toPoint())
                    return True
                if not event.buttons():
                    edge = self._edge_at(event.position().toPoint())
                    self._central.setCursor(QCursor(_CURSOR_FOR_EDGE[edge]) if edge else QCursor(Qt.ArrowCursor))
            elif event_type == QEvent.Type.Enter:
                # central only ever receives MouseMove on its own thin
                # RESIZE_MARGIN band (everywhere else is covered by the title
                # bar/tabs), so re-entering the window over a child widget --
                # or from outside the app entirely -- produced no MouseMove
                # on central to refresh the cursor, leaving a stale resize
                # icon stuck until the user happened to hover the margin
                # again. Enter fires reliably on every re-entry regardless of
                # where the cursor lands, so refresh the cursor from it too.
                if self._resize_edge is None:
                    edge = self._edge_at(self._central.mapFromGlobal(QCursor.pos()))
                    self._central.setCursor(QCursor(_CURSOR_FOR_EDGE[edge]) if edge else QCursor(Qt.ArrowCursor))
            elif event_type == QEvent.Type.Leave:
                # Moving from the margin onto a child widget (tabs, title
                # bar) also needs a reset -- once a child is under the
                # cursor, central stops receiving MouseMove entirely.
                if self._resize_edge is None:
                    self._central.unsetCursor()
            elif event_type == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    edge = self._edge_at(event.position().toPoint())
                    if edge is not None:
                        self._resize_edge = edge
                        self._resize_start_geometry = QRect(self.geometry())
                        self._resize_start_pos = event.globalPosition().toPoint()
                        return True
            elif event_type == QEvent.Type.MouseButtonRelease:
                if self._resize_edge is not None:
                    self._resize_edge = None
                    self._central.unsetCursor()
                    return True
        return super().eventFilter(obj, event)

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

    def _on_download_blocked_by_theme(self, info_hash: str) -> None:
        QMessageBox.warning(
            self,
            "Nyet.",
            "Ce téléchargement reste en pause : sous le thème CCCP, on ne "
            "possède pas de fichiers, on les partage. Changez de thème si "
            "vous tenez vraiment à télécharger quelque chose.",
        )

    def _on_theme_downloads_paused(self, count: int) -> None:
        plural = "s" if count > 1 else ""
        QMessageBox.information(
            self,
            "Décret du Politburo",
            f"{count} téléchargement{plural} en cours {'ont' if count > 1 else 'a'} été "
            f"mis en pause : la propriété individuelle de fichiers est désormais "
            f"interdite. Vos partages, eux, continuent -- et rapportent 3 fois "
            f"plus de gloire collective.",
        )

    def _on_shutdown_dialog_finished(self) -> None:
        self._shutdown_dialog = None

    def set_theme(self, theme_id: str, appearance_mode: str) -> None:
        app = QGuiApplication.instance()
        if app is not None:
            apply_theme(app, theme_id, appearance_mode)
        self._apply_window_style(theme_id, appearance_mode)

    def _apply_window_style(self, theme_id: str, appearance_mode: str) -> None:
        style = title_bar_style_for(theme_id, appearance_mode)
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
