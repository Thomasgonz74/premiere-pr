"""ProfileSecurityBridge.copyLogToClipboard puts the log on the clipboard
Python-side instead of shipping it through QWebChannel to the page."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import QApplication

from torrent2000.config.paths import get_logs_dir
from torrent2000.config.settings import Settings
from torrent2000.ui.web.bridge_profile_security import ProfileSecurityBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_copy_log_sets_the_clipboard_without_returning_the_text(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    (get_logs_dir() / "torrent2000.log").write_text("line one\nline two\n", encoding="utf-8")

    result = ProfileSecurityBridge(Settings()).copyLogToClipboard()

    assert result == {"ok": True}
    assert QApplication.clipboard().text() == "line one\nline two\n"


def test_copy_log_reports_a_clipboard_that_did_not_take_the_text(tmp_path, monkeypatch):
    # A failed OleSetClipboard is only a Qt warning: setText returns normally.
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    (get_logs_dir() / "torrent2000.log").write_text("fresh log\n", encoding="utf-8")
    QApplication.clipboard().setText("something else")
    monkeypatch.setattr(QClipboard, "setText", lambda self, text, *args: None)

    result = ProfileSecurityBridge(Settings()).copyLogToClipboard()

    assert result == {"ok": False, "clipboardError": True}
