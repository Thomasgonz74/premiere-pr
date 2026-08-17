import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.i18n.translator import set_language, tr
from torrent2000.ui.tabs.profile_sections import ConfigImportExportSection

RAW_OS_ERROR_TEXT = "Permission denied"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def french_ui():
    set_language("fr")


@pytest.fixture
def section():
    return ConfigImportExportSection(Settings())


def test_export_failure_shows_translated_message_not_raw_exception(section, tmp_path):
    target = tmp_path / "config.json"
    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getSaveFileName", return_value=(str(target), "")),
        patch.object(Path, "write_text", side_effect=OSError(13, RAW_OS_ERROR_TEXT)),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.warning") as mock_warning,
        patch("torrent2000.ui.tabs.profile_sections.logger") as mock_logger,
    ):
        QTest.mouseClick(section.export_button, Qt.LeftButton)

    mock_warning.assert_called_once()
    _, title, message = mock_warning.call_args[0]
    assert title == tr("profile_tab.export_failed_title")
    assert message == tr("profile_tab.export_failed_message")
    assert RAW_OS_ERROR_TEXT not in message
    mock_logger.warning.assert_called_once()
    assert RAW_OS_ERROR_TEXT in str(mock_logger.warning.call_args)


def test_import_os_error_shows_translated_message_not_raw_exception(section, tmp_path):
    missing = tmp_path / "does_not_exist.json"
    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getOpenFileName", return_value=(str(missing), "")),
        patch.object(Path, "read_text", side_effect=OSError(13, RAW_OS_ERROR_TEXT)),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.warning") as mock_warning,
        patch("torrent2000.ui.tabs.profile_sections.logger") as mock_logger,
    ):
        QTest.mouseClick(section.import_button, Qt.LeftButton)

    mock_warning.assert_called_once()
    _, title, message = mock_warning.call_args[0]
    assert title == tr("profile_tab.import_failed_title")
    assert message == tr("profile_tab.import_failed_message_os")
    assert RAW_OS_ERROR_TEXT not in message
    mock_logger.warning.assert_called_once()
    assert RAW_OS_ERROR_TEXT in str(mock_logger.warning.call_args)


def test_import_invalid_json_shows_translated_message_not_raw_exception(section, tmp_path):
    bad_file = tmp_path / "corrupted.json"
    bad_file.write_text("not valid json {{{", encoding="utf-8")

    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getOpenFileName", return_value=(str(bad_file), "")),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.warning") as mock_warning,
        patch("torrent2000.ui.tabs.profile_sections.logger") as mock_logger,
    ):
        QTest.mouseClick(section.import_button, Qt.LeftButton)

    mock_warning.assert_called_once()
    _, title, message = mock_warning.call_args[0]
    assert title == tr("profile_tab.import_failed_title")
    assert message == tr("profile_tab.import_failed_message_invalid")
    assert "Expecting" not in message
    assert "line 1 column" not in message
    mock_logger.warning.assert_called_once()


def test_import_os_and_invalid_json_produce_different_messages():
    assert tr("profile_tab.import_failed_message_os") != tr("profile_tab.import_failed_message_invalid")


def test_json_files_still_parse_after_edits():
    i18n_dir = Path(__file__).resolve().parent.parent / "resources" / "i18n"
    for path in i18n_dir.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
