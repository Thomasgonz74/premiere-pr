import logging
import sys

from PySide6.QtWidgets import QApplication

from torrent2000 import APP_NAME
from torrent2000.config.paths import get_history_db_path, get_logs_dir, get_rss_seen_db_path, get_stats_db_path
from torrent2000.config.settings import Settings
from torrent2000.engine.auto_shutdown_service import AutoShutdownService
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.engine.disk_space_monitor import DiskSpaceMonitor
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.rss_seen_store import RssSeenStore
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.watch_folder_service import WatchFolderService
from torrent2000.i18n.translator import set_language
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.history_store import HistoryStore
from torrent2000.stats.service import StatsService
from torrent2000.stats.store import StatsStore
from torrent2000.ui.main_window import MainWindow
from torrent2000.ui.notifications import NotificationService
from torrent2000.ui.theme.theme_manager import apply_theme, init_theme_runtime


def _setup_logging() -> None:
    log_path = get_logs_dir() / "torrent2000.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def main() -> int:
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    init_theme_runtime(app)

    settings = Settings.load()
    set_language(settings.language)
    apply_theme(app, settings.theme, settings.appearance_mode)

    session_manager = SessionManager(settings)
    stats_store = StatsStore(get_stats_db_path())
    stats_service = StatsService(stats_store, session_manager, settings)
    share_limit_service = ShareLimitService(session_manager)
    bandwidth_scheduler = BandwidthScheduler(session_manager, settings)
    notification_service = NotificationService(session_manager, share_limit_service, settings, app)
    history_store = HistoryStore(get_history_db_path())
    history_service = HistoryService(history_store, session_manager)
    rss_seen_store = RssSeenStore(get_rss_seen_db_path())
    rss_feed_service = RssFeedService(session_manager, settings, rss_seen_store)
    watch_folder_service = WatchFolderService(session_manager, settings)
    disk_space_monitor = DiskSpaceMonitor(session_manager, settings)
    auto_shutdown_service = AutoShutdownService(session_manager, settings)
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
    )
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
