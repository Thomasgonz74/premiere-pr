import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from torrent2000.ui.tabs.profile_sections import DiagnosticsSection


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def section():
    return DiagnosticsSection()


def test_open_logs_button_opens_the_logs_folder(section, tmp_path, monkeypatch):
    monkeypatch.setattr("torrent2000.ui.tabs.profile_sections.get_logs_dir", lambda: tmp_path)

    with patch("torrent2000.ui.tabs.profile_sections.QDesktopServices.openUrl") as mock_open:
        QTest.mouseClick(section.open_logs_button, Qt.LeftButton)

    mock_open.assert_called_once()
    opened_url = mock_open.call_args[0][0]
    assert opened_url.toString() == QUrl.fromLocalFile(str(tmp_path)).toString()


def test_copy_log_button_copies_the_log_contents_to_the_clipboard(section, tmp_path, monkeypatch):
    monkeypatch.setattr("torrent2000.ui.tabs.profile_sections.get_logs_dir", lambda: tmp_path)
    log_content = "2026-08-09 12:00:00 INFO Session started\n2026-08-09 12:00:01 INFO Torrent added"
    (tmp_path / "torrent2000.log").write_text(log_content, encoding="utf-8")

    with patch("torrent2000.ui.tabs.profile_sections.QMessageBox.information") as mock_info:
        QTest.mouseClick(section.copy_log_button, Qt.LeftButton)

    assert QApplication.clipboard().text() == log_content
    mock_info.assert_called_once()


def test_copy_log_button_shows_a_message_when_no_log_file_exists_yet(section, tmp_path, monkeypatch):
    monkeypatch.setattr("torrent2000.ui.tabs.profile_sections.get_logs_dir", lambda: tmp_path)
    QApplication.clipboard().setText("unchanged")

    with patch("torrent2000.ui.tabs.profile_sections.QMessageBox.information") as mock_info:
        QTest.mouseClick(section.copy_log_button, Qt.LeftButton)

    mock_info.assert_called_once()
    assert QApplication.clipboard().text() == "unchanged"


def test_write_to_persists_nothing(section):
    section.write_to(MagicMock())  # must not raise -- action-only section


def test_retranslate_ui_reapplies_the_current_language_strings(section):
    section.retranslate_ui()  # must not raise
    assert section.title() != ""
