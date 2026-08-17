import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from torrent2000.config.settings import Settings
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.history_store import HistoryStore
from torrent2000.ui.tabs.profile_sections import HistorySection
from torrent2000.ui.tabs.profile_tab import ProfileTab


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_tab(av_scan_enabled: bool = False, battery_pause_enabled: bool = False):
    settings = Settings()
    settings.scan_completed_files_with_defender = av_scan_enabled
    settings.pause_on_battery_enabled = battery_pause_enabled
    settings.save = MagicMock()
    widget = ProfileTab(MagicMock(), MagicMock(), MagicMock(), MagicMock(), settings, MagicMock())
    return widget, settings


# --------------------------------------------------------------- antivirus


def test_av_scan_checkbox_initializes_from_settings_enabled():
    widget, _ = _make_tab(av_scan_enabled=True)
    assert widget.security_section.av_scan_checkbox.isChecked() is True


def test_av_scan_checkbox_initializes_from_settings_disabled():
    widget, _ = _make_tab(av_scan_enabled=False)
    assert widget.security_section.av_scan_checkbox.isChecked() is False


def test_av_scan_checkbox_round_trips_through_write_to():
    widget, settings = _make_tab(av_scan_enabled=False)
    widget.security_section.av_scan_checkbox.setChecked(True)

    widget._on_save_clicked()

    assert settings.scan_completed_files_with_defender is True


def test_av_scan_checkbox_unchecking_persists_false():
    widget, settings = _make_tab(av_scan_enabled=True)
    widget.security_section.av_scan_checkbox.setChecked(False)

    widget._on_save_clicked()

    assert settings.scan_completed_files_with_defender is False


# ----------------------------------------------------------------- battery


def test_battery_pause_checkbox_initializes_from_settings_enabled():
    widget, _ = _make_tab(battery_pause_enabled=True)
    assert widget.battery_section.battery_pause_checkbox.isChecked() is True


def test_battery_pause_checkbox_initializes_from_settings_disabled():
    widget, _ = _make_tab(battery_pause_enabled=False)
    assert widget.battery_section.battery_pause_checkbox.isChecked() is False


def test_battery_pause_checkbox_round_trips_through_write_to():
    widget, settings = _make_tab(battery_pause_enabled=False)
    widget.battery_section.battery_pause_checkbox.setChecked(True)

    widget._on_save_clicked()

    assert settings.pause_on_battery_enabled is True


def test_battery_pause_checkbox_unchecking_persists_false():
    widget, settings = _make_tab(battery_pause_enabled=True)
    widget.battery_section.battery_pause_checkbox.setChecked(False)

    widget._on_save_clicked()

    assert settings.pause_on_battery_enabled is False


def test_retranslate_ui_does_not_raise_with_new_sections():
    widget, _ = _make_tab()
    widget.retranslate_ui()  # must not raise


# ------------------------------------------------------------- clear history


def _history_section_with_entries(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    from PySide6.QtCore import QObject, Signal

    class FakeSessionManager(QObject):
        torrent_status_updated = Signal(str, object)
        torrent_removed = Signal(str)

    from dataclasses import dataclass

    @dataclass
    class FakeRecord:
        info_hash: str
        name: str = "Example.Torrent"
        total_size: int = 1000
        all_time_downloaded: int = 500
        all_time_uploaded: int = 250

    fake_sm = FakeSessionManager()
    service = HistoryService(store, fake_sm)
    for i in range(2):
        fake_sm.torrent_status_updated.emit(f"hash{i}", FakeRecord(info_hash=f"hash{i}", name=f"Torrent{i}"))
        fake_sm.torrent_removed.emit(f"hash{i}")

    section = HistorySection(service)
    return section, service, store


def test_clear_history_button_clears_after_confirmation(tmp_path):
    section, service, store = _history_section_with_entries(tmp_path)
    assert len(service.all_entries()) == 2
    assert section.history_table.rowCount() == 2

    with patch(
        "torrent2000.ui.tabs.profile_sections.QMessageBox.question", return_value=QMessageBox.Yes
    ) as mock_question:
        QTest.mouseClick(section.clear_history_button, Qt.LeftButton)

    mock_question.assert_called_once()
    assert service.all_entries() == []
    assert store.all_entries() == []
    assert section.history_table.rowCount() == 0


def test_clear_history_button_does_nothing_when_cancelled(tmp_path):
    section, service, store = _history_section_with_entries(tmp_path)

    with patch("torrent2000.ui.tabs.profile_sections.QMessageBox.question", return_value=QMessageBox.No):
        QTest.mouseClick(section.clear_history_button, Qt.LeftButton)

    assert len(service.all_entries()) == 2
    assert len(store.all_entries()) == 2
