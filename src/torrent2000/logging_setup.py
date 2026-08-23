"""Rotating log file + global uncaught-exception capture, shared by every
entry point (native run.py historically, run_web_spike.py now) -- extracted
from the old torrent2000.app module so it survives independently of which
UI is wired up to it.
"""

import logging
import logging.handlers
import sys

from torrent2000.config.paths import get_logs_dir


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
