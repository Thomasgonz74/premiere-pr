"""Regression tests for downloads_tab.py's ETA column, health indicator, and
private-torrent badge (Phase 2 audit finding)."""

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from torrent2000.engine.torrent_item import TorrentRecord, TorrentState, TrackerInfo
from torrent2000.i18n.translator import tr
from torrent2000.ui.tabs.downloads_tab import DownloadsTab, _eta_text, _health_status, _name_text, _name_tooltip


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- ETA column

def test_eta_text_computes_remaining_time_from_rate_and_progress():
    # remaining = 1000 * (1 - 0.5) = 500 bytes / 100 B/s = 5s
    record = TorrentRecord(info_hash="h", total_size=1000, progress=0.5, download_rate=100)
    assert _eta_text(record) == "5s"


def test_eta_text_is_dash_when_download_rate_is_zero():
    record = TorrentRecord(info_hash="h", total_size=1000, progress=0.5, download_rate=0)
    assert _eta_text(record) == "—"


def test_eta_text_is_dash_when_already_complete():
    record = TorrentRecord(info_hash="h", total_size=1000, progress=1.0, download_rate=100)
    assert _eta_text(record) == "—"


def test_downloads_tab_eta_column_shows_computed_value():
    record = TorrentRecord(
        info_hash="h1", name="X", total_size=2000, progress=0.5, download_rate=200, state=TorrentState.DOWNLOADING
    )
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]

    tab = DownloadsTab(session_manager)

    row = tab._rows["h1"]
    assert tab.table.item(row, 2).text() == _eta_text(record)


def test_downloads_tab_eta_column_updates_on_status_update():
    record = TorrentRecord(info_hash="h1", name="X", total_size=1000, progress=0.0, download_rate=0)
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]

    tab = DownloadsTab(session_manager)
    row = tab._rows["h1"]
    assert tab.table.item(row, 2).text() == "—"

    updated = TorrentRecord(info_hash="h1", name="X", total_size=1000, progress=0.25, download_rate=250)
    tab._on_status_updated("h1", updated)

    # remaining = 1000 * 0.75 = 750 / 250 = 3s
    assert tab.table.item(row, 2).text() == "3s"


# ------------------------------------------------------------- health status

def test_health_status_blank_for_paused():
    assert _health_status(TorrentRecord(info_hash="h", state=TorrentState.PAUSED)) == ""


def test_health_status_blank_for_awaiting_analysis():
    assert _health_status(TorrentRecord(info_hash="h", state=TorrentState.AWAITING_ANALYSIS)) == ""


def test_health_status_blank_for_checking_metadata():
    assert _health_status(TorrentRecord(info_hash="h", state=TorrentState.CHECKING_METADATA)) == ""


def test_health_status_blank_for_queued():
    assert _health_status(TorrentRecord(info_hash="h", state=TorrentState.QUEUED)) == ""


def test_health_status_critical_for_error_state():
    assert _health_status(TorrentRecord(info_hash="h", state=TorrentState.ERROR)) == "critical"


def test_health_status_critical_when_no_seeds_and_tracker_erroring():
    record = TorrentRecord(
        info_hash="h",
        state=TorrentState.DOWNLOADING,
        num_seeds=0,
        num_peers=3,
        trackers=[TrackerInfo(url="http://t", last_error="connection refused")],
    )
    assert _health_status(record) == "critical"


def test_health_status_warning_when_no_seeds_but_no_tracker_error():
    record = TorrentRecord(info_hash="h", state=TorrentState.DOWNLOADING, num_seeds=0, num_peers=3)
    assert _health_status(record) == "warning"


def test_health_status_warning_when_no_peers():
    record = TorrentRecord(info_hash="h", state=TorrentState.SEEDING, num_seeds=2, num_peers=0)
    assert _health_status(record) == "warning"


def test_health_status_healthy_when_peers_and_seeds_present():
    record = TorrentRecord(info_hash="h", state=TorrentState.DOWNLOADING, num_seeds=5, num_peers=5)
    assert _health_status(record) == "healthy"


def test_downloads_tab_applies_health_background_and_tooltip_on_state_cell():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.ERROR)
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]

    tab = DownloadsTab(session_manager)

    row = tab._rows["h1"]
    item = tab.table.item(row, 6)
    assert item.background().style() != Qt.NoBrush
    assert item.toolTip() == tr("downloads_tab.health_critical_tooltip")


def test_downloads_tab_clears_health_background_for_meaningless_state():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.PAUSED)
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]

    tab = DownloadsTab(session_manager)

    row = tab._rows["h1"]
    item = tab.table.item(row, 6)
    assert item.background().style() == Qt.NoBrush
    assert item.toolTip() == ""


# ------------------------------------------------------------- private badge

def test_name_text_prefixes_lock_emoji_for_private_torrent():
    record = TorrentRecord(info_hash="h", name="Secret", is_private=True)
    text = _name_text(record)
    assert text != "Secret"
    assert text.endswith("Secret")


def test_name_text_unchanged_for_non_private_torrent():
    record = TorrentRecord(info_hash="h", name="Public", is_private=False)
    assert _name_text(record) == "Public"


def test_name_tooltip_explains_private_status():
    record = TorrentRecord(info_hash="h", name="Secret", is_private=True)
    tooltip = _name_tooltip(record)
    assert "Secret" in tooltip
    assert "DHT" in tooltip


def test_name_tooltip_is_just_the_name_when_not_private():
    record = TorrentRecord(info_hash="h", name="Public", is_private=False)
    assert _name_tooltip(record) == "Public"


def test_downloads_tab_shows_private_badge_in_name_cell():
    record = TorrentRecord(info_hash="h1", name="Secret", is_private=True, state=TorrentState.DOWNLOADING)
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]

    tab = DownloadsTab(session_manager)

    row = tab._rows["h1"]
    assert tab.table.item(row, 0).text() != "Secret"
    assert "Secret" in tab.table.item(row, 0).text()
    assert "DHT" in tab.table.item(row, 0).toolTip()


def test_downloads_tab_hides_private_badge_for_public_torrent():
    record = TorrentRecord(info_hash="h1", name="Public", is_private=False, state=TorrentState.DOWNLOADING)
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]

    tab = DownloadsTab(session_manager)

    row = tab._rows["h1"]
    assert tab.table.item(row, 0).text() == "Public"
    assert tab.table.item(row, 0).toolTip() == "Public"


def test_downloads_tab_private_badge_updates_on_status_update():
    record = TorrentRecord(info_hash="h1", name="X", is_private=False)
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]

    tab = DownloadsTab(session_manager)
    row = tab._rows["h1"]
    assert tab.table.item(row, 0).text() == "X"

    # is_private is resolved lazily by SessionManager once metadata arrives.
    updated = TorrentRecord(info_hash="h1", name="X", is_private=True)
    tab._on_status_updated("h1", updated)

    assert tab.table.item(row, 0).text() != "X"
    assert "X" in tab.table.item(row, 0).text()
