import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from torrent2000 import APP_NAME
from torrent2000.config.settings import Settings
from torrent2000.engine.anthem_player import AnthemPlayer
from torrent2000.engine.auto_shutdown_service import AutoShutdownService
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor, free_space_mb
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.torrent_item import TorrentState
from torrent2000.engine.update_checker import UpdateChecker
from torrent2000.i18n.translator import set_language, tr
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.service import StatsService
from torrent2000.ui.frameless_resize import RESIZE_MARGIN, FramelessResizeController, compute_min_window_size
from torrent2000.ui.tabs.add_tab import AddTorrentTab
from torrent2000.ui.tabs.downloads_tab import DownloadsTab
from torrent2000.ui.tabs.profile_tab import ProfileTab
from torrent2000.ui.tabs.rss_tab import RssTab
from torrent2000.ui.tabs.share_tab import ShareTab
from torrent2000.theme_ids import CCCP_THEME_ID
from torrent2000.ui.theme.theme_manager import apply_theme, cursor_for_theme, title_bar_style_for
from torrent2000.ui.widgets.app_title_bar import AppTitleBar
from torrent2000.ui.widgets.table_helpers import confirm_and_remove
from torrent2000.ui.widgets.propaganda_panel import PANEL_WIDTH, CccpPropagandaPanel
from torrent2000.ui.widgets.shutdown_countdown_dialog import ShutdownCountdownDialog
from torrent2000.utils.formatting import human_rate, human_size

logger = logging.getLogger(__name__)

# Icon/accent color for the propaganda panel, per appearance mode -- dark_hc
# needs yellow like every other accent in that mode, not red.
_CCCP_PANEL_ACCENT_COLORS = {"light": "#CC1B1B", "dark": "#E2261F", "dark_hc": "#FFFF00"}


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
        update_checker: UpdateChecker,
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
        self._update_checker = update_checker
        self._pending_release_url = ""
        # Guards against a double shutdown() call: closeEvent runs it directly
        # when minimizing to tray is off (or unavailable), while a tray "Quitter"
        # always goes through QApplication.aboutToQuit instead -- see closeEvent
        # and _on_about_to_quit below.
        self._shutdown_done = False
        update_checker.update_available.connect(self._on_update_available)
        update_checker.installer_verified.connect(self._on_installer_verified)
        update_checker.installer_verification_failed.connect(self._on_installer_verification_failed)
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.aboutToQuit.connect(self._on_about_to_quit)

        self.setWindowTitle(APP_NAME)
        # The native Windows title bar can't be restyled to match any of
        # these themes (QSS doesn't reach OS-owned window chrome), so the
        # window runs frameless and AppTitleBar below stands in for it.
        # Frameless also means the OS's own edge-resize handling is gone --
        # see FramelessResizeController for the replacement.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.resize(980, 640)

        central = QWidget(self)
        central.setObjectName("centralWidget")
        central.setMouseTracking(True)
        self._central = central
        outer_layout = QVBoxLayout(central)
        # A thin margin, left deliberately free of any child widget, is what
        # lets central (and FramelessResizeController's eventFilter) actually
        # receive mouse events near the window's edges -- if the title
        # bar/tabs filled the window right to its border, they would be the
        # widgets under the cursor there instead, and this window would
        # never see the event.
        outer_layout.setContentsMargins(RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN)
        outer_layout.setSpacing(0)
        self._resize_controller = FramelessResizeController(self, central)

        self._title_bar = AppTitleBar(APP_NAME, title_bar_style_for(settings.theme, settings.appearance_mode), central)
        outer_layout.addWidget(self._title_bar)

        # Tabs + the CCCP theme's propaganda side panel sit side by side --
        # the panel is only ever shown while that theme is active (see
        # _set_cccp_panel_active), as extra window width reserved for it.
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        tabs = QTabWidget(central)
        tabs.setObjectName("mainTabs")
        self._add_tab = AddTorrentTab(session_manager, settings)
        tabs.addTab(self._add_tab, tr("tabs.add"))
        self._downloads_tab_index = tabs.count()
        self._downloads_tab = DownloadsTab(session_manager)
        tabs.addTab(self._downloads_tab, tr("tabs.downloads"))
        self._share_tab = ShareTab(session_manager, share_limit_service, settings)
        tabs.addTab(self._share_tab, tr("tabs.share"))
        self._rss_tab = RssTab(session_manager, rss_feed_service, settings)
        tabs.addTab(self._rss_tab, tr("tabs.rss"))
        self._profile_tab = ProfileTab(
            session_manager, stats_service, bandwidth_scheduler, history_service, settings, disk_space_monitor
        )
        self._profile_tab.theme_changed.connect(self.set_theme)
        self._profile_tab.language_changed.connect(self._on_language_changed)
        self._anthem_player = AnthemPlayer(settings.audio_volume)
        self._profile_tab.volume_changed.connect(self._anthem_player.set_volume)
        tabs.addTab(self._profile_tab, tr("tabs.profile"))
        content_row.addWidget(tabs, 1)
        self._tabs = tabs

        self._propaganda_panel = CccpPropagandaPanel(central)
        self._propaganda_panel.hide()
        content_row.addWidget(self._propaganda_panel)

        outer_layout.addLayout(content_row, 1)

        self._add_tab.torrent_started.connect(self._on_torrent_started)
        auto_shutdown_service.shutdown_countdown_started.connect(self._on_shutdown_countdown_started)
        session_manager.download_blocked_by_theme.connect(self._on_download_blocked_by_theme)
        session_manager.theme_downloads_paused.connect(self._on_theme_downloads_paused)

        # Slim aggregate status row -- not a QStatusBar, since this window
        # runs frameless with custom chrome (see the class docstring-level
        # comment on setWindowFlags above). Sits between the tabs/panel and
        # the size-grip row, both in outer_layout below.
        status_row = QHBoxLayout()
        status_row.setContentsMargins(6, 2, 6, 2)
        self._status_active_label = QLabel(central)
        status_row.addWidget(self._status_active_label)
        self._status_paused_label = QLabel(central)
        status_row.addWidget(self._status_paused_label)
        self._status_error_label = QLabel(central)
        status_row.addWidget(self._status_error_label)
        status_row.addSpacing(16)
        self._status_download_rate_label = QLabel(central)
        status_row.addWidget(self._status_download_rate_label)
        self._status_upload_rate_label = QLabel(central)
        status_row.addWidget(self._status_upload_rate_label)
        status_row.addSpacing(16)
        self._status_free_space_label = QLabel(central)
        status_row.addWidget(self._status_free_space_label)
        status_row.addStretch(1)
        self._turtle_mode_button = QPushButton(tr("main_window.turtle_mode_button"), central)
        self._turtle_mode_button.setCheckable(True)
        self._turtle_mode_button.setToolTip(tr("main_window.turtle_mode_tooltip"))
        self._turtle_mode_button.toggled.connect(self._bandwidth_scheduler.set_turtle_mode)
        status_row.addWidget(self._turtle_mode_button)
        outer_layout.addLayout(status_row)
        session_manager.torrent_status_updated.connect(self._on_status_row_update)
        self._update_status_row()

        # Global shortcuts, active regardless of which tab/widget has focus.
        self._shortcut_open_torrent = QShortcut(QKeySequence("Ctrl+O"), self)
        self._shortcut_open_torrent.activated.connect(self._on_open_torrent_shortcut)
        self._shortcut_next_tab = QShortcut(QKeySequence("Ctrl+Tab"), self)
        self._shortcut_next_tab.activated.connect(self._on_next_tab_shortcut)
        self._shortcut_remove_torrent = QShortcut(QKeySequence(Qt.Key_Delete), self)
        self._shortcut_remove_torrent.activated.connect(self._on_remove_torrent_shortcut)
        self._shortcut_pause_resume = QShortcut(QKeySequence(Qt.Key_Space), self)
        self._shortcut_pause_resume.activated.connect(self._on_pause_resume_shortcut)

        # A visible QSizeGrip reinforces the bottom-right corner as a resize
        # handle (FramelessResizeController above already lets you drag from
        # any edge or corner of the window, but a corner grip is a more
        # discoverable affordance for the same gesture). Kept in its own full-width row
        # below content_row (rather than nested under just the tabs) so it
        # stays anchored at the window's actual bottom-right corner even
        # when the propaganda panel is showing.
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 2, 2)
        grip_row.addStretch(1)
        self._size_grip = QSizeGrip(central)
        grip_row.addWidget(self._size_grip, 0, Qt.AlignBottom | Qt.AlignRight)
        outer_layout.addLayout(grip_row)

        # Computed now rather than up front: needs the title bar/tab bar/
        # status row/grip row already built, so this reflects actual
        # chrome/DPI instead of a guessed constant -- see
        # compute_min_window_size's docstring for why it's chrome-only
        # (title bar, tab bar, status row, grip row) rather than the whole
        # central widget.
        chrome_hints = [
            self._title_bar.minimumSizeHint(),
            tabs.tabBar().minimumSizeHint(),
            status_row.minimumSize(),
            grip_row.minimumSize(),
        ]
        min_size = compute_min_window_size(chrome_hints, RESIZE_MARGIN)
        self.setMinimumSize(*min_size)
        self._resize_controller.set_min_size(min_size)

        self.setCentralWidget(central)

        self._cccp_panel_active = False
        self._apply_window_style(settings.theme, settings.appearance_mode)

    def _on_torrent_started(self) -> None:
        # Switching to the Downloads tab right after starting a download is
        # more intuitive than leaving the user on the Add tab wondering if
        # anything happened.
        self._tabs.setCurrentIndex(self._downloads_tab_index)

    # ------------------------------------------------------------ shortcuts

    def _on_open_torrent_shortcut(self) -> None:
        self._tabs.setCurrentWidget(self._add_tab)
        self._add_tab.browse_button.click()

    def _on_next_tab_shortcut(self) -> None:
        self._tabs.setCurrentIndex((self._tabs.currentIndex() + 1) % self._tabs.count())

    def _selected_downloads_info_hash(self) -> str | None:
        # Only meaningful while the Downloads tab is the one on screen.
        # Delegates to DownloadsTab.selected_info_hash(), which is None
        # unless exactly one row is selected -- the table allows multi-select
        # (ExtendedSelection) since the bulk-actions context menu was added,
        # so grabbing table.selectedItems()[0] here would silently act on an
        # arbitrary torrent out of the selection instead of a clear single
        # target.
        if self._tabs.currentWidget() is not self._downloads_tab:
            return None
        return self._downloads_tab.selected_info_hash()

    def _on_remove_torrent_shortcut(self) -> None:
        info_hash = self._selected_downloads_info_hash()
        if not info_hash:
            return
        # Same confirm-with-optional-delete-files dialog as the Downloads
        # tab's own Remove button, so Delete can't bypass it as an
        # accidental-slip shortcut for the exact same destructive action.
        confirm_and_remove(
            self,
            on_click=lambda: self._session_manager.remove_torrent(info_hash),
            on_click_with_files=lambda: self._session_manager.remove_torrent(info_hash, delete_files=True),
        )

    def _on_pause_resume_shortcut(self) -> None:
        info_hash = self._selected_downloads_info_hash()
        if not info_hash:
            return
        record = self._session_manager.get_record(info_hash)
        if record is None:
            return
        if record.state == TorrentState.PAUSED:
            self._session_manager.resume_torrent(info_hash)
        else:
            self._session_manager.pause_torrent(info_hash)

    # ------------------------------------------------------------ status row

    def _on_status_row_update(self, info_hash: str, record) -> None:
        self._update_status_row()

    def _update_status_row(self) -> None:
        active = paused = error = 0
        total_download_rate = 0
        total_upload_rate = 0
        for record in self._session_manager.all_records():
            if record.state == TorrentState.PAUSED:
                paused += 1
            elif record.state == TorrentState.ERROR:
                error += 1
            else:
                active += 1
            total_download_rate += record.download_rate
            total_upload_rate += record.upload_rate

        self._status_active_label.setText(tr("main_window.status_active", count=active))
        self._status_paused_label.setText(tr("main_window.status_paused", count=paused))
        self._status_error_label.setText(tr("main_window.status_error", count=error))
        self._status_download_rate_label.setText(tr("main_window.status_download_rate", rate=human_rate(total_download_rate)))
        self._status_upload_rate_label.setText(tr("main_window.status_upload_rate", rate=human_rate(total_upload_rate)))

        free_mb = free_space_mb(self._settings.default_download_dir)
        free_text = human_size(free_mb * 1024 * 1024) if free_mb is not None else "—"
        self._status_free_space_label.setText(tr("main_window.status_free_space", free=free_text))

    def open_source(self, source: str) -> None:
        """Called with a .torrent path or magnet: URI when the app is
        launched via the installer's file/protocol association (double-
        clicking a .torrent file, or clicking a magnet link in a browser)."""
        self._tabs.setCurrentWidget(self._add_tab)
        if source.lower().startswith("magnet:"):
            self._add_tab.open_magnet(source)
        else:
            self._add_tab.open_torrent_file(source)

    def _on_shutdown_countdown_started(self, delay_seconds: int) -> None:
        if self._shutdown_dialog is not None:
            return  # a countdown is already showing
        dialog = ShutdownCountdownDialog(delay_seconds, action=self._settings.auto_shutdown_action, parent=self)
        dialog.cancelled.connect(self._auto_shutdown_service.cancel_shutdown)
        dialog.finished.connect(self._on_shutdown_dialog_finished)
        self._shutdown_dialog = dialog
        dialog.show()

    def _on_download_blocked_by_theme(self, info_hash: str) -> None:
        QMessageBox.warning(self, tr("cccp.nyet_title"), tr("cccp.download_blocked_message"))

    def _on_theme_downloads_paused(self, count: int) -> None:
        key = "cccp.downloads_paused_singular" if count == 1 else "cccp.downloads_paused_plural"
        QMessageBox.information(self, tr("cccp.politburo_decree_title"), tr(key, count=count))

    def _on_shutdown_dialog_finished(self) -> None:
        self._shutdown_dialog = None

    def _on_update_available(self, version: str, release_url: str) -> None:
        # Custom buttons (not QMessageBox's built-in Yes/No) so their labels
        # follow the app's own language setting rather than the OS locale,
        # matching how every other dialog here already resolves through tr().
        box = QMessageBox(self)
        box.setWindowTitle(tr("update.title"))
        box.setText(tr("update.message", version=version))
        download_button = box.addButton(tr("update.download_button"), QMessageBox.AcceptRole)
        box.addButton(tr("update.later_button"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is download_button:
            self._pending_release_url = release_url
            self._update_checker.download_verified_installer()
        else:
            self._settings.dismissed_update_version = version
            self._settings.save()

    def _on_installer_verified(self, local_path: str) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(tr("update.verified_title"))
        box.setText(tr("update.verified_message"))
        launch_button = box.addButton(tr("update.launch_button"), QMessageBox.AcceptRole)
        box.addButton(tr("update.launch_later_button"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is launch_button:
            subprocess.Popen([local_path])
            # Torrent2000.exe stays locked by Windows while this process is
            # running, and the installer needs to overwrite that exact file
            # -- close() (not a raw exit) so the normal closeEvent teardown
            # (stats/session flush) still runs before the file lock is freed.
            self.close()
        else:
            # "Later" or the dialog was dismissed without a choice -- the
            # verified copy in %TEMP% won't be launched, so it would
            # otherwise sit there forever (only the next update download
            # sweeps stale copies). Delete it now; best-effort since nothing
            # else depends on this file.
            try:
                Path(local_path).unlink()
            except OSError:
                pass

    def _on_installer_verification_failed(self, reason: str) -> None:
        logger.warning("Update installer verification failed (%s); opening the release page instead", reason)
        if self._pending_release_url:
            QDesktopServices.openUrl(QUrl(self._pending_release_url))

    def set_theme(self, theme_id: str, appearance_mode: str) -> None:
        app = QGuiApplication.instance()
        if app is not None:
            apply_theme(app, theme_id, appearance_mode)
        self._apply_window_style(theme_id, appearance_mode)

    def _on_language_changed(self, language_code: str) -> None:
        set_language(language_code)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._title_bar.set_title(APP_NAME)
        self._title_bar.retranslate_ui()
        self._tabs.setTabText(self._tabs.indexOf(self._add_tab), tr("tabs.add"))
        self._tabs.setTabText(self._tabs.indexOf(self._downloads_tab), tr("tabs.downloads"))
        self._tabs.setTabText(self._tabs.indexOf(self._share_tab), tr("tabs.share"))
        self._tabs.setTabText(self._tabs.indexOf(self._rss_tab), tr("tabs.rss"))
        self._tabs.setTabText(self._tabs.indexOf(self._profile_tab), tr("tabs.profile"))
        self._add_tab.retranslate_ui()
        self._downloads_tab.retranslate_ui()
        self._share_tab.retranslate_ui()
        self._rss_tab.retranslate_ui()
        self._profile_tab.retranslate_ui()
        self._propaganda_panel.retranslate_ui()
        self._turtle_mode_button.setText(tr("main_window.turtle_mode_button"))
        self._turtle_mode_button.setToolTip(tr("main_window.turtle_mode_tooltip"))
        self._update_status_row()

    def _apply_window_style(self, theme_id: str, appearance_mode: str) -> None:
        style = title_bar_style_for(theme_id, appearance_mode)
        self._title_bar.apply_style(style)
        self._resize_controller.set_corner_radius(style.window_corner_radius)
        # Set on the window itself (not per-widget): Qt's cursor inheritance
        # cascades this to every descendant that hasn't set its own cursor
        # (QGroupBox, QTabBar, table backgrounds...), while QLineEdit/
        # QSpinBox keep the native IBeam they already set explicitly. QSS has
        # no `cursor` property, so this can't be done from the .qss files.
        cursor = cursor_for_theme(theme_id)
        if cursor is not None:
            self.setCursor(cursor)
        else:
            self.unsetCursor()
        self._set_cccp_panel_active(theme_id == CCCP_THEME_ID)
        if theme_id == CCCP_THEME_ID:
            self._propaganda_panel.set_accent_color(_CCCP_PANEL_ACCENT_COLORS.get(appearance_mode, "#CC1B1B"))

    def _set_cccp_panel_active(self, active: bool) -> None:
        # The panel is extra window width, not space carved out of the
        # existing content -- growing/shrinking the window on toggle is
        # what "il faudrait rajouter une largeur supplémentaire" asked for,
        # rather than the tabs just getting narrower to make room.
        if active == self._cccp_panel_active:
            return
        self._cccp_panel_active = active
        if active:
            self._propaganda_panel.show()
            self._propaganda_panel.start()
            self._anthem_player.start()
            self.resize(self.width() + PANEL_WIDTH, self.height())
        else:
            self._propaganda_panel.stop()
            self._propaganda_panel.hide()
            self._anthem_player.stop()
            self.resize(max(self.minimumWidth(), self.width() - PANEL_WIDTH), self.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_controller.update_corner_mask()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            self._title_bar.refresh_maximize_glyph()
            self._resize_controller.update_corner_mask()

    def closeEvent(self, event) -> None:
        if self._settings.minimize_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            return
        self._shutdown()
        super().closeEvent(event)

    def _on_about_to_quit(self) -> None:
        # Covers the tray menu's "Quitter" path, which calls app.quit()
        # directly rather than closing the window (see app.py).
        self._shutdown()

    def _shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._stats_service.shutdown()
        self._session_manager.shutdown()
