import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import ProxySettings, Settings
from torrent2000.danger_scanner.models import FileEntry, FileRisk, RiskLevel, ScanResult
from torrent2000.engine.torrent_item import TorrentRecord
from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.security_center_section import SecurityCenterSection, risk_report_summary


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _session_manager(records: list[TorrentRecord] | None = None) -> MagicMock:
    manager = MagicMock()
    manager.all_records.return_value = records or []
    return manager


def _flagged_scan_result() -> ScanResult:
    file = FileEntry(index=0, path="setup.exe", size=1024, executable_flag=True)
    file_risk = FileRisk(file=file, score=90, level=RiskLevel.CRITICAL, reasons=["exe"])
    return ScanResult(file_risks=[file_risk], overall_score=90, flagged_indices=[0])


def _safe_scan_result() -> ScanResult:
    file = FileEntry(index=0, path="movie.mkv", size=1024)
    file_risk = FileRisk(file=file, score=0, level=RiskLevel.SAFE, reasons=[])
    return ScanResult(file_risks=[file_risk], overall_score=0, flagged_indices=[])


# ---------------------------------------------------------------- settings display


def test_proxy_kill_switch_active_when_enabled_and_forced():
    settings = Settings()
    settings.proxy = ProxySettings(enabled=True, force_proxy=True)
    section = SecurityCenterSection(settings, _session_manager())

    assert section.proxy_status_label.text() == tr("security_center.status_active")
    assert section.proxy_note_label.text() == tr("security_center.kill_switch_active_note")


def test_proxy_enabled_but_kill_switch_off_shows_the_risk_note():
    settings = Settings()
    settings.proxy = ProxySettings(enabled=True, force_proxy=False)
    section = SecurityCenterSection(settings, _session_manager())

    assert section.proxy_status_label.text() == tr("security_center.status_active")
    assert section.proxy_note_label.text() == tr("security_center.kill_switch_inactive_note")


def test_proxy_disabled_shows_inactive_and_direct_traffic_note():
    settings = Settings()
    settings.proxy = ProxySettings(enabled=False)
    section = SecurityCenterSection(settings, _session_manager())

    assert section.proxy_status_label.text() == tr("security_center.status_inactive")
    assert section.proxy_note_label.text() == tr("security_center.proxy_disabled_note")


def test_discovery_restriction_reflects_settings():
    settings_on = Settings()
    settings_on.restrict_discovery = True
    section_on = SecurityCenterSection(settings_on, _session_manager())
    assert section_on.discovery_status_label.text() == tr("security_center.status_active")

    settings_off = Settings()
    settings_off.restrict_discovery = False
    section_off = SecurityCenterSection(settings_off, _session_manager())
    assert section_off.discovery_status_label.text() == tr("security_center.status_inactive")


@pytest.mark.parametrize(
    "mode, expected_key",
    [
        ("forced", "encryption_mode.forced"),
        ("enabled", "encryption_mode.enabled"),
        ("disabled", "encryption_mode.disabled"),
    ],
)
def test_encryption_mode_label_matches_settings(mode, expected_key):
    settings = Settings()
    settings.encryption_mode = mode
    section = SecurityCenterSection(settings, _session_manager())

    assert section.encryption_status_label.text() == tr(expected_key)


def test_network_interface_shows_configured_value():
    settings = Settings()
    settings.network_interface = "192.168.1.42"
    section = SecurityCenterSection(settings, _session_manager())

    assert section.interface_status_label.text() == "192.168.1.42"


def test_network_interface_falls_back_to_default_label_when_empty():
    settings = Settings()
    settings.network_interface = ""
    section = SecurityCenterSection(settings, _session_manager())

    assert section.interface_status_label.text() == tr("profile_tab.interface_default")


# ---------------------------------------------------------------- risk report summary


def test_risk_report_summary_counts_only_scanned_and_flagged_torrents():
    records = [
        TorrentRecord(info_hash="a", danger_report=_flagged_scan_result()),
        TorrentRecord(info_hash="b", danger_report=_safe_scan_result()),
        TorrentRecord(info_hash="c", danger_report=None),  # not yet analyzed
    ]

    scanned, flagged = risk_report_summary(_session_manager(records))

    assert scanned == 2
    assert flagged == 1


def test_risk_row_shows_no_scans_message_when_nothing_analyzed_yet():
    settings = Settings()
    section = SecurityCenterSection(settings, _session_manager([]))

    assert section.risk_status_label.text() == tr("security_center.risk_no_scans")


def test_risk_row_shows_summary_with_counts_when_torrents_were_scanned():
    records = [
        TorrentRecord(info_hash="a", danger_report=_flagged_scan_result()),
        TorrentRecord(info_hash="b", danger_report=_safe_scan_result()),
    ]
    settings = Settings()
    section = SecurityCenterSection(settings, _session_manager(records))

    assert section.risk_status_label.text() == tr("security_center.risk_summary", scanned=2, flagged=1)


# ---------------------------------------------------------------- refresh button


def test_refresh_button_reflects_settings_changed_after_construction():
    settings = Settings()
    settings.proxy = ProxySettings(enabled=False)
    settings.restrict_discovery = False
    section = SecurityCenterSection(settings, _session_manager())

    assert section.proxy_status_label.text() == tr("security_center.status_inactive")
    assert section.discovery_status_label.text() == tr("security_center.status_inactive")

    # Settings mutated in place after construction (e.g. Save was clicked
    # elsewhere in the Profile tab) -- the section itself has no way to know
    # unless the user clicks Refresh.
    settings.proxy.enabled = True
    settings.proxy.force_proxy = True
    settings.restrict_discovery = True

    QTest.mouseClick(section.refresh_button, Qt.LeftButton)

    assert section.proxy_status_label.text() == tr("security_center.status_active")
    assert section.proxy_note_label.text() == tr("security_center.kill_switch_active_note")
    assert section.discovery_status_label.text() == tr("security_center.status_active")


def test_refresh_reflects_new_torrents_added_after_construction():
    manager = _session_manager([])
    settings = Settings()
    section = SecurityCenterSection(settings, manager)
    assert section.risk_status_label.text() == tr("security_center.risk_no_scans")

    manager.all_records.return_value = [TorrentRecord(info_hash="a", danger_report=_flagged_scan_result())]
    section.refresh()

    assert section.risk_status_label.text() == tr("security_center.risk_summary", scanned=1, flagged=1)


# ---------------------------------------------------------------- section contract


def test_write_to_persists_nothing():
    settings = Settings()
    section = SecurityCenterSection(settings, _session_manager())
    before = Settings()

    section.write_to(settings)

    assert settings == before  # unchanged -- read-only section


def test_retranslate_ui_reapplies_current_language_strings_and_refreshes():
    settings = Settings()
    section = SecurityCenterSection(settings, _session_manager())

    section.retranslate_ui()  # must not raise

    assert section.title() == tr("security_center.group")
    assert section.refresh_button.text() == tr("security_center.refresh_button")
