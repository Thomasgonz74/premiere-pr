import json
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from torrent2000.config.settings import Settings
from torrent2000.i18n.translator import set_language, tr
from torrent2000.ui.tabs.profile_sections import ConfigImportExportSection

REAL_PROXY_PASSWORD = "hunter2-super-secret"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def french_ui():
    set_language("fr")


@pytest.fixture
def settings_with_proxy_password():
    settings = Settings()
    settings.proxy.enabled = True
    settings.proxy.proxy_type = "socks5_pw"
    settings.proxy.host = "proxy.example.com"
    settings.proxy.port = 1080
    settings.proxy.username = "alice"
    settings.proxy.password = REAL_PROXY_PASSWORD
    return settings


@pytest.fixture
def section(settings_with_proxy_password):
    return ConfigImportExportSection(settings_with_proxy_password)


def test_export_never_writes_real_proxy_password(section, tmp_path):
    target = tmp_path / "config.json"
    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getSaveFileName", return_value=(str(target), "")),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.information"),
    ):
        QTest.mouseClick(section.export_button, Qt.LeftButton)

    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["proxy"]["password"] == ""
    assert REAL_PROXY_PASSWORD not in target.read_text(encoding="utf-8")
    # Every other proxy field is preserved -- only the password is redacted.
    assert written["proxy"]["host"] == "proxy.example.com"
    assert written["proxy"]["username"] == "alice"


def test_export_redacts_password_regardless_of_its_value(tmp_path):
    for pw in ("", "short", "a very long password with spaces & symbols !@#$"):
        settings = Settings()
        settings.proxy.password = pw
        local_section = ConfigImportExportSection(settings)
        target = tmp_path / f"config_{len(pw)}.json"
        with (
            patch(
                "torrent2000.ui.tabs.profile_sections.QFileDialog.getSaveFileName",
                return_value=(str(target), ""),
            ),
            patch("torrent2000.ui.tabs.profile_sections.QMessageBox.information"),
        ):
            QTest.mouseClick(local_section.export_button, Qt.LeftButton)
        written = json.loads(target.read_text(encoding="utf-8"))
        assert written["proxy"]["password"] == ""


def test_import_rejects_file_with_unreconstructible_shape_before_any_write(section, tmp_path):
    bad_file = tmp_path / "not_a_config.json"
    # Valid JSON, but a completely different shape (a bare list) -- must be
    # rejected by validation, never even reach the write step.
    bad_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    config_path = tmp_path / "real_config.json"

    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getOpenFileName", return_value=(str(bad_file), "")),
        patch("torrent2000.ui.tabs.profile_sections.get_config_path", return_value=config_path),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.warning") as mock_warning,
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.question") as mock_question,
    ):
        QTest.mouseClick(section.import_button, Qt.LeftButton)

    mock_question.assert_not_called()
    mock_warning.assert_called_once()
    _, title, message = mock_warning.call_args[0]
    assert title == tr("profile_tab.import_failed_title")
    assert message == tr("profile_tab.import_failed_message_schema")
    assert message != tr("profile_tab.import_failed_message_invalid")
    assert not config_path.exists()


def test_import_rejects_file_with_malformed_proxy_substructure(section, tmp_path):
    bad_file = tmp_path / "bad_proxy.json"
    bad_file.write_text(json.dumps({"proxy": "not-an-object", "schema_version": 1}), encoding="utf-8")
    config_path = tmp_path / "real_config.json"

    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getOpenFileName", return_value=(str(bad_file), "")),
        patch("torrent2000.ui.tabs.profile_sections.get_config_path", return_value=config_path),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.warning") as mock_warning,
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.question") as mock_question,
    ):
        QTest.mouseClick(section.import_button, Qt.LeftButton)

    mock_question.assert_not_called()
    mock_warning.assert_called_once()
    assert not config_path.exists()


def test_import_valid_file_requires_confirmation_and_declining_writes_nothing(section, tmp_path):
    good_file = tmp_path / "good_config.json"
    good_file.write_text(json.dumps({"schema_version": 1, "language": "fr"}), encoding="utf-8")
    config_path = tmp_path / "real_config.json"

    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getOpenFileName", return_value=(str(good_file), "")),
        patch("torrent2000.ui.tabs.profile_sections.get_config_path", return_value=config_path),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.question", return_value=QMessageBox.No) as mock_question,
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.information") as mock_information,
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.warning") as mock_warning,
    ):
        QTest.mouseClick(section.import_button, Qt.LeftButton)

    mock_question.assert_called_once()
    _, title, message, *_rest = mock_question.call_args[0]
    assert title == tr("profile_tab.import_confirm_title")
    assert message == tr("profile_tab.import_confirm_message")
    mock_warning.assert_not_called()
    mock_information.assert_not_called()
    assert not config_path.exists()


def test_import_valid_file_writes_after_confirmation(section, tmp_path):
    good_file = tmp_path / "good_config.json"
    payload = {"schema_version": 1, "language": "fr", "proxy": {"host": "1.2.3.4", "port": 8080}}
    good_file.write_text(json.dumps(payload), encoding="utf-8")
    config_path = tmp_path / "real_config.json"

    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getOpenFileName", return_value=(str(good_file), "")),
        patch("torrent2000.ui.tabs.profile_sections.get_config_path", return_value=config_path),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.question", return_value=QMessageBox.Yes) as mock_question,
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.information") as mock_information,
    ):
        QTest.mouseClick(section.import_button, Qt.LeftButton)

    mock_question.assert_called_once()
    assert config_path.exists()
    written = json.loads(config_path.read_text(encoding="utf-8"))
    # The original parsed payload is written verbatim on success -- import
    # validation/confirmation only gates the write, it doesn't transform it.
    assert written == payload
    mock_information.assert_called_once()


def test_import_confirm_message_distinct_from_schema_failure_message():
    assert tr("profile_tab.import_confirm_message") != tr("profile_tab.import_failed_message_schema")
    assert tr("profile_tab.import_failed_message_schema") != tr("profile_tab.import_failed_message_invalid")
