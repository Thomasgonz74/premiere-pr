"""Crash-logging tests: rotating log file and uncaught-exception capture.

These exercise _setup_logging() / _install_excepthook() directly -- no
QApplication or MainWindow involved, per the app's local-only, no-telemetry
diagnostics philosophy.
"""

import logging
import logging.handlers
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from torrent2000.app import _install_excepthook, _setup_logging
from torrent2000.config.paths import get_logs_dir


def _reset_root_logger(root: logging.Logger) -> None:
    for handler in root.handlers[:]:
        root.removeHandler(handler)


@pytest.fixture
def isolated_root_logger():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    yield root

    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    for handler in original_handlers:
        root.addHandler(handler)
    root.setLevel(original_level)


@pytest.fixture
def restore_excepthook():
    original = sys.excepthook
    yield
    sys.excepthook = original


def test_setup_logging_installs_rotating_file_handler(tmp_path, monkeypatch, isolated_root_logger, restore_excepthook):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    _reset_root_logger(isolated_root_logger)

    _setup_logging()

    file_handlers = [
        h for h in isolated_root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 5 * 1024 * 1024
    assert file_handlers[0].backupCount == 3


def test_setup_logging_writes_into_logs_dir(tmp_path, monkeypatch, isolated_root_logger, restore_excepthook):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    _reset_root_logger(isolated_root_logger)

    _setup_logging()

    assert (get_logs_dir() / "torrent2000.log").exists()


def test_setup_logging_replaces_excepthook(tmp_path, monkeypatch, isolated_root_logger, restore_excepthook):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    _reset_root_logger(isolated_root_logger)
    default_hook = sys.excepthook

    _setup_logging()

    assert sys.excepthook is not default_hook


def test_excepthook_logs_critical_then_calls_default(tmp_path, monkeypatch, isolated_root_logger, restore_excepthook):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    _reset_root_logger(isolated_root_logger)
    _setup_logging()

    default_hook_calls = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *args: default_hook_calls.append(args))

    try:
        raise ValueError("boom")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()

    sys.excepthook(exc_type, exc_value, exc_tb)
    for handler in isolated_root_logger.handlers:
        handler.flush()

    assert len(default_hook_calls) == 1
    assert default_hook_calls[0][0] is ValueError

    log_contents = (get_logs_dir() / "torrent2000.log").read_text(encoding="utf-8")
    assert "CRITICAL" in log_contents
    assert "Uncaught exception" in log_contents
    assert "boom" in log_contents


def test_install_excepthook_alone_does_not_touch_handlers(isolated_root_logger, restore_excepthook):
    _reset_root_logger(isolated_root_logger)
    default_hook = sys.excepthook

    _install_excepthook()

    assert sys.excepthook is not default_hook
    assert isolated_root_logger.handlers == []
