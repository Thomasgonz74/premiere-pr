import csv
import os
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.stats.history_service import HistoryService
from torrent2000.stats.history_store import HistoryStore
from torrent2000.ui.tabs.profile_sections import (
    GeneralSettingsSection,
    HistorySection,
    NetworkPrivacySection,
    _list_local_ipv6_interfaces,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeFamily:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeAddr:
    def __init__(self, family_name: str, address: str) -> None:
        self.family = _FakeFamily(family_name)
        self.address = address


# --------------------------------------------------------------------- IPv6


def test_list_local_ipv6_interfaces_excludes_link_local_and_loopback():
    fake_addrs = {
        "Ethernet": [
            _FakeAddr("AF_INET", "192.168.1.5"),
            _FakeAddr("AF_INET6", "fe80::1234%12"),  # link-local -- excluded
            _FakeAddr("AF_INET6", "2001:db8::1"),  # global -- kept
        ],
        "Loopback": [
            _FakeAddr("AF_INET6", "::1"),  # loopback -- excluded
        ],
    }
    with patch("torrent2000.ui.tabs.profile_sections.psutil.net_if_addrs", return_value=fake_addrs):
        entries = _list_local_ipv6_interfaces()

    assert entries == [("Ethernet (2001:db8::1)", "2001:db8::1")]


def test_list_local_ipv6_interfaces_empty_is_not_a_crash():
    with patch("torrent2000.ui.tabs.profile_sections.psutil.net_if_addrs", return_value={}):
        assert _list_local_ipv6_interfaces() == []


def test_list_local_ipv6_interfaces_on_real_machine_does_not_crash():
    # Best-effort: may be empty in CI, but must never raise.
    assert isinstance(_list_local_ipv6_interfaces(), list)


def test_network_privacy_section_interface_combo_lists_both_families():
    settings = Settings()
    with (
        patch(
            "torrent2000.ui.tabs.profile_sections._list_local_ipv4_interfaces",
            return_value=[("Ethernet (192.168.1.5)", "192.168.1.5")],
        ),
        patch(
            "torrent2000.ui.tabs.profile_sections._list_local_ipv6_interfaces",
            return_value=[("Ethernet (2001:db8::1)", "2001:db8::1")],
        ),
    ):
        section = NetworkPrivacySection(settings)

    values = [section.interface_combo.itemData(i) for i in range(section.interface_combo.count())]
    assert "192.168.1.5" in values
    assert "2001:db8::1" in values


def test_network_privacy_section_can_select_and_persist_an_ipv6_interface():
    settings = Settings()
    with (
        patch("torrent2000.ui.tabs.profile_sections._list_local_ipv4_interfaces", return_value=[]),
        patch(
            "torrent2000.ui.tabs.profile_sections._list_local_ipv6_interfaces",
            return_value=[("Ethernet (2001:db8::1)", "2001:db8::1")],
        ),
    ):
        section = NetworkPrivacySection(settings)

    idx = section.interface_combo.findData("2001:db8::1")
    assert idx >= 0
    section.interface_combo.setCurrentIndex(idx)

    section.write_to(settings)

    assert settings.network_interface == "2001:db8::1"


# --------------------------------------------------------------- CSV export


@dataclass
class _FakeRecord:
    info_hash: str
    name: str = "Example.Torrent"
    total_size: int = 1_000_000
    all_time_downloaded: int = 500_000
    all_time_uploaded: int = 250_000


class _FakeSessionManager(QObject):
    torrent_status_updated = Signal(str, object)
    torrent_removed = Signal(str)


def _history_section_with_entries(tmp_path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    fake_sm = _FakeSessionManager()
    service = HistoryService(store, fake_sm)
    for i in range(2):
        fake_sm.torrent_status_updated.emit(f"hash{i}", _FakeRecord(info_hash=f"hash{i}", name=f"Torrent{i}"))
        fake_sm.torrent_removed.emit(f"hash{i}")
    section = HistorySection(service)
    return section, service, store


def test_export_csv_writes_raw_byte_values_not_human_readable_strings(tmp_path):
    section, service, _store = _history_section_with_entries(tmp_path)
    out_path = tmp_path / "export.csv"

    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getSaveFileName", return_value=(str(out_path), "")),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.information") as mock_info,
    ):
        QTest.mouseClick(section.export_csv_button, Qt.LeftButton)

    mock_info.assert_called_once()
    assert out_path.exists()

    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    assert rows[0] == section._columns()
    entries = service.all_entries()
    assert len(rows) == 1 + len(entries)
    written_names = {row[0] for row in rows[1:]}
    assert written_names == {"Torrent0", "Torrent1"}
    for row in rows[1:]:
        name, size, downloaded, uploaded, finished_at = row
        # Raw byte counts, not human_size() strings like "976.6 KB".
        assert size == "1000000"
        assert downloaded == "500000"
        assert uploaded == "250000"
        assert finished_at  # non-empty ISO timestamp


def test_export_csv_cancelled_dialog_does_nothing(tmp_path):
    section, _service, _store = _history_section_with_entries(tmp_path)

    with patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getSaveFileName", return_value=("", "")):
        QTest.mouseClick(section.export_csv_button, Qt.LeftButton)  # must not raise


def test_export_csv_failure_shows_translated_message_not_raw_exception(tmp_path):
    section, _service, _store = _history_section_with_entries(tmp_path)
    out_path = tmp_path / "export.csv"
    raw_os_error_text = "Permission denied"

    with (
        patch("torrent2000.ui.tabs.profile_sections.QFileDialog.getSaveFileName", return_value=(str(out_path), "")),
        patch("torrent2000.ui.tabs.profile_sections.open", side_effect=OSError(13, raw_os_error_text)),
        patch("torrent2000.ui.tabs.profile_sections.QMessageBox.warning") as mock_warning,
        patch("torrent2000.ui.tabs.profile_sections.logger") as mock_logger,
    ):
        QTest.mouseClick(section.export_csv_button, Qt.LeftButton)

    mock_warning.assert_called_once()
    _, title, message = mock_warning.call_args[0]
    from torrent2000.i18n.translator import tr

    assert title == tr("profile_tab.csv_export_failed_title")
    assert message == tr("profile_tab.csv_export_failed_message")
    assert raw_os_error_text not in message
    mock_logger.warning.assert_called_once()


# ---------------------------------------------------------- minimize to tray


def _general_section(minimize_to_tray: bool) -> tuple[GeneralSettingsSection, Settings]:
    settings = Settings()
    settings.minimize_to_tray = minimize_to_tray
    with patch("torrent2000.ui.tabs.profile_sections.startup_registration.is_launch_at_startup_enabled", return_value=False):
        section = GeneralSettingsSection(settings, MagicMock())
    return section, settings


def test_minimize_to_tray_checkbox_initializes_from_settings_enabled():
    section, _settings = _general_section(minimize_to_tray=True)
    assert section.minimize_to_tray_checkbox.isChecked() is True


def test_minimize_to_tray_checkbox_initializes_from_settings_disabled():
    section, _settings = _general_section(minimize_to_tray=False)
    assert section.minimize_to_tray_checkbox.isChecked() is False


def test_minimize_to_tray_checkbox_round_trips_through_write_to():
    section, settings = _general_section(minimize_to_tray=False)
    section.minimize_to_tray_checkbox.setChecked(True)

    with patch("torrent2000.ui.tabs.profile_sections.startup_registration.set_launch_at_startup"):
        section.write_to(settings)

    assert settings.minimize_to_tray is True


def test_minimize_to_tray_checkbox_unchecking_persists_false():
    section, settings = _general_section(minimize_to_tray=True)
    section.minimize_to_tray_checkbox.setChecked(False)

    with patch("torrent2000.ui.tabs.profile_sections.startup_registration.set_launch_at_startup"):
        section.write_to(settings)

    assert settings.minimize_to_tray is False


def test_general_section_retranslate_ui_does_not_raise():
    section, _settings = _general_section(minimize_to_tray=True)
    section.retranslate_ui()  # must not raise
