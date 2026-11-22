"""ProfileSecurityBridge.copyLogToClipboard puts the log on the clipboard
Python-side instead of shipping it through QWebChannel to the page."""

import os
from unittest.mock import MagicMock

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


def test_a_config_with_wrong_typed_values_is_refused_and_never_stops_a_launch(tmp_path, monkeypatch):
    """Imported, a "fast" rate limit reached lt.session() at the next launch:
    the app exited at every start until config.json was deleted by hand."""
    import json

    from torrent2000.config.paths import get_config_path

    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    wrong = {"download_rate_limit_kbps": "fast", "max_active_downloads": "many"}
    import_path = tmp_path / "wrong.json"
    import_path.write_text(json.dumps(wrong), encoding="utf-8")

    assert ProfileSecurityBridge(Settings()).importConfig(str(import_path))["ok"] is False

    get_config_path().write_text(json.dumps(wrong), encoding="utf-8")  # edited by hand
    loaded = Settings.load()
    assert (loaded.download_rate_limit_kbps, loaded.max_active_downloads) == (0, 8)


def test_after_an_import_saving_a_page_says_nothing_was_saved(tmp_path, monkeypatch):
    """The import holds config.json until the next launch: "Settings saved."
    then contradicted it, and the change was gone after the restart."""
    from torrent2000.i18n.translator import tr
    from torrent2000.ui.web import bridge_profile_general
    from torrent2000.ui.web.bridge_profile_general import ProfileGeneralBridge

    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    # The real HKCU Run key is never read or written.
    monkeypatch.setattr(bridge_profile_general.startup_registration, "is_launch_at_startup_enabled", lambda: False)
    monkeypatch.setattr(bridge_profile_general.startup_registration, "set_launch_at_startup", lambda on: None)
    settings = Settings.load()
    security = ProfileSecurityBridge(settings)
    exported = tmp_path / "export.json"
    assert security.exportConfig(str(exported)) == {"ok": True}
    assert security.importConfig(str(exported)) == {"ok": True}

    result = ProfileGeneralBridge(session_manager=MagicMock(), settings=settings).saveSettings({"downloadRateLimitKbps": 4321})

    assert result == {"ok": False, "error": tr("web.profile_security.save_held_after_import")}
