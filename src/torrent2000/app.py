import logging
import logging.handlers
import sys

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from torrent2000 import APP_NAME
from torrent2000.config.paths import get_history_db_path, get_logs_dir, get_rss_seen_db_path, get_stats_db_path
from torrent2000.config.settings import Settings
from torrent2000.engine.antivirus_scan_service import AntivirusScanService
from torrent2000.engine.auto_shutdown_service import AutoShutdownService
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.engine.battery_pause_service import BatteryPauseService
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor
from torrent2000.engine.remote_server import RemoteAccessServer
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.rss_seen_store import RssSeenStore
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.single_instance import SingleInstanceGuard
from torrent2000.engine.update_checker import UpdateChecker
from torrent2000.engine.watch_folder_service import WatchFolderService
from torrent2000.i18n.translator import set_language
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.history_store import HistoryStore
from torrent2000.stats.service import StatsService
from torrent2000.stats.store import StatsStore
from torrent2000.ui.main_window import MainWindow
from torrent2000.ui.notifications import NotificationService
from torrent2000.ui.onboarding_dialog import maybe_show_onboarding
from torrent2000.ui.theme.theme_manager import apply_theme, init_theme_runtime


def _setup_logging() -> None:
    log_path = get_logs_dir() / "torrent2000.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
    )
    _install_excepthook()


def _install_excepthook() -> None:
    logger = logging.getLogger(__name__)

    def _log_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _log_uncaught_exception


class _ButtonClickFocusFilter(QObject):
    """App-wide sweep (installed once on QApplication -- Qt delivers every
    event in the whole app through a filter installed there) that switches
    ordinary QPushButtons from the Qt default Qt.StrongFocus to Qt.TabFocus,
    the same policy app_title_bar.py's caption buttons already use. TabFocus
    still lets Tab reach the button and show a focus ring (accessibility,
    see tasks #60/#61); it just stops a plain mouse click from also leaving
    that ring on, which under several QSS themes renders almost identical to
    :hover and looks like a stuck-hover bug. One filter here instead of a
    setFocusPolicy call in each of the ~17 files that build a QPushButton."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Polish and isinstance(obj, QPushButton):
            if obj.focusPolicy() == Qt.FocusPolicy.StrongFocus:
                obj.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        return False


def main() -> int:
    # Qt6 auto-syncs some native-adjacent chrome (e.g. QMessageBox's frame)
    # with the Windows-wide dark mode setting, bypassing our own QSS -- this
    # app has its own complete light/dark/dark_hc system per theme and must
    # be the sole source of truth for its own appearance, independent of
    # whatever the user has Windows itself set to. Passed as a separate argv
    # to QApplication (not appended to sys.argv itself), since sys.argv[1]
    # below is still read positionally as a forwarded .torrent/magnet path.
    app = QApplication([sys.argv[0], "-platform", "windows:darkmode=0"])
    # Checked before any other startup work (logging setup, Settings/session
    # construction) so a second launch -- e.g. double-clicking another
    # .torrent file while the app is already open, now that the installer
    # registers that file association -- forwards its argument and exits as
    # cheaply as possible instead of racing a second libtorrent session.
    guard = SingleInstanceGuard()
    if not guard.try_become_primary(sys.argv[1] if len(sys.argv) > 1 else ""):
        return 0

    # Parented to app so it isn't garbage-collected once main() returns here.
    app.installEventFilter(_ButtonClickFocusFilter(app))

    _setup_logging()
    app.setApplicationName(APP_NAME)
    init_theme_runtime(app)

    settings = Settings.load()
    set_language(settings.language)
    apply_theme(app, settings.theme, settings.appearance_mode)

    session_manager = SessionManager(settings)
    # Off by default (see Settings.remote_access_enabled) -- only actually
    # binds a socket if the user had already opted in on a previous launch.
    remote_access_server = RemoteAccessServer(session_manager, settings)
    if settings.remote_access_enabled:
        remote_access_server.start()
    app.aboutToQuit.connect(remote_access_server.stop)
    stats_store = StatsStore(get_stats_db_path())
    stats_service = StatsService(stats_store, session_manager, settings)
    share_limit_service = ShareLimitService(session_manager, settings)
    # Share-limit saves are debounced (see ShareLimitService._schedule_save);
    # flush any still-pending write so a burst right before quitting isn't lost.
    app.aboutToQuit.connect(share_limit_service.flush_pending_save)
    bandwidth_scheduler = BandwidthScheduler(session_manager, settings)
    notification_service = NotificationService(session_manager, share_limit_service, settings, app)
    history_store = HistoryStore(get_history_db_path())
    history_service = HistoryService(history_store, session_manager)
    rss_seen_store = RssSeenStore(get_rss_seen_db_path())
    rss_feed_service = RssFeedService(session_manager, settings, rss_seen_store)
    watch_folder_service = WatchFolderService(session_manager, settings)
    disk_space_monitor = DiskSpaceMonitor(session_manager, settings)
    auto_shutdown_service = AutoShutdownService(session_manager, settings)
    battery_pause_service = BatteryPauseService(session_manager, settings)
    antivirus_scan_service = AntivirusScanService(session_manager, settings)
    update_checker = UpdateChecker(settings)
    window = MainWindow(
        session_manager,
        stats_service,
        share_limit_service,
        bandwidth_scheduler,
        history_service,
        settings,
        rss_feed_service,
        disk_space_monitor,
        auto_shutdown_service,
        update_checker,
    )
    # Second-launch arguments arriving later, forwarded by SingleInstanceGuard
    # (empty when a later launch had none, e.g. the exe was just reopened).
    guard.argument_received.connect(lambda source: window.open_source(source) if source else None)
    if len(sys.argv) > 1:
        window.open_source(sys.argv[1])

    def _restore_window() -> None:
        window.show()
        window.raise_()
        window.activateWindow()

    notification_service.show_requested.connect(_restore_window)
    notification_service.quit_requested.connect(app.quit)

    window.show()
    maybe_show_onboarding(window, settings)
    # Delayed so the update check's network request doesn't compete with the
    # rest of startup (session restore, stats DB open, etc).
    QTimer.singleShot(3000, update_checker.check_now)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
