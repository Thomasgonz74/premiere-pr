import logging
import sys

from PySide6.QtWidgets import QApplication

from torrent2000 import APP_NAME
from torrent2000.config.paths import get_logs_dir, get_stats_db_path
from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.stats.service import StatsService
from torrent2000.stats.store import StatsStore
from torrent2000.ui.main_window import MainWindow
from torrent2000.ui.theme.luna_theme import apply_luna_theme


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
    apply_luna_theme(app)

    settings = Settings.load()
    session_manager = SessionManager(settings)
    stats_store = StatsStore(get_stats_db_path())
    stats_service = StatsService(stats_store, session_manager)
    window = MainWindow(session_manager, stats_service, settings)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
