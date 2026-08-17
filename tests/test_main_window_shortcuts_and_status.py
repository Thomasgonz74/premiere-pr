import os
from datetime import datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.engine.bandwidth_scheduler import BandwidthScheduler
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState
from torrent2000.i18n.translator import tr
from torrent2000.ui.main_window import MainWindow
from torrent2000.utils.formatting import human_rate


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _make_window(session_manager=None, bandwidth_scheduler=None):
    session_manager = session_manager or MagicMock()
    bandwidth_scheduler = bandwidth_scheduler or MagicMock()
    win = MainWindow(
        session_manager,
        MagicMock(),
        MagicMock(),
        bandwidth_scheduler,
        MagicMock(),
        Settings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    return win, session_manager, bandwidth_scheduler


def _select_downloads_row(win, session_manager, record):
    # get_record must resolve to the same real TorrentRecord the row was
    # built from -- both DownloadsTab's own selection handler and the
    # MainWindow shortcut handlers look it up this way.
    session_manager.get_record.return_value = record
    win._downloads_tab._add_row(record)
    row = win._downloads_tab._rows[record.info_hash]
    win._downloads_tab.table.selectRow(row)


# --------------------------------------------------------------- shortcuts


def test_shortcut_key_sequences_registered():
    win, _, _ = _make_window()
    try:
        assert win._shortcut_open_torrent.key() == QKeySequence("Ctrl+O")
        assert win._shortcut_next_tab.key() == QKeySequence("Ctrl+Tab")
        assert win._shortcut_remove_torrent.key() == QKeySequence(Qt.Key_Delete)
        assert win._shortcut_pause_resume.key() == QKeySequence(Qt.Key_Space)
    finally:
        win.close()


def test_ctrl_o_switches_to_add_tab_and_triggers_its_browse_action():
    win, _, _ = _make_window()
    try:
        win._tabs.setCurrentWidget(win._downloads_tab)
        with patch("torrent2000.ui.tabs.add_tab.QFileDialog.getOpenFileName", return_value=("", "")) as mock_dialog:
            win._shortcut_open_torrent.activated.emit()
        assert win._tabs.currentWidget() is win._add_tab
        mock_dialog.assert_called_once()
    finally:
        win.close()


def test_ctrl_tab_cycles_forward_and_wraps():
    win, _, _ = _make_window()
    try:
        win._tabs.setCurrentIndex(0)
        win._shortcut_next_tab.activated.emit()
        assert win._tabs.currentIndex() == 1

        win._tabs.setCurrentIndex(win._tabs.count() - 1)
        win._shortcut_next_tab.activated.emit()
        assert win._tabs.currentIndex() == 0
    finally:
        win.close()


def test_delete_removes_the_selected_torrent_when_downloads_tab_active():
    # Delete routes through the same confirm_and_remove dialog as the
    # Downloads tab's own Remove button (see table_helpers.py) -- mocking
    # its QMessageBox and choosing "remove only" mirrors
    # test_table_helpers_remove_confirm.py's own pattern.
    win, session_manager, _ = _make_window()
    try:
        win._tabs.setCurrentWidget(win._downloads_tab)
        record = TorrentRecord(info_hash="abc123", name="Foo", state=TorrentState.DOWNLOADING)
        _select_downloads_row(win, session_manager, record)

        mock_box_cls = MagicMock()
        box = mock_box_cls.return_value
        remove_only = object()
        box.addButton.side_effect = [remove_only, object(), object()]
        box.clickedButton.return_value = remove_only

        with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
            win._shortcut_remove_torrent.activated.emit()

        session_manager.remove_torrent.assert_called_once_with("abc123")
    finally:
        win.close()


def test_delete_is_a_noop_when_downloads_tab_not_active():
    win, session_manager, _ = _make_window()
    try:
        record = TorrentRecord(info_hash="abc123", name="Foo", state=TorrentState.DOWNLOADING)
        _select_downloads_row(win, session_manager, record)
        win._tabs.setCurrentWidget(win._add_tab)

        win._shortcut_remove_torrent.activated.emit()

        session_manager.remove_torrent.assert_not_called()
    finally:
        win.close()


def test_delete_is_a_noop_without_a_selection():
    win, session_manager, _ = _make_window()
    try:
        win._tabs.setCurrentWidget(win._downloads_tab)
        win._shortcut_remove_torrent.activated.emit()
        session_manager.remove_torrent.assert_not_called()
    finally:
        win.close()


def test_space_pauses_a_downloading_torrent():
    win, session_manager, _ = _make_window()
    try:
        win._tabs.setCurrentWidget(win._downloads_tab)
        record = TorrentRecord(info_hash="abc123", name="Foo", state=TorrentState.DOWNLOADING)
        _select_downloads_row(win, session_manager, record)

        win._shortcut_pause_resume.activated.emit()

        session_manager.pause_torrent.assert_called_once_with("abc123")
        session_manager.resume_torrent.assert_not_called()
    finally:
        win.close()


def test_space_resumes_a_paused_torrent():
    win, session_manager, _ = _make_window()
    try:
        win._tabs.setCurrentWidget(win._downloads_tab)
        record = TorrentRecord(info_hash="abc123", name="Foo", state=TorrentState.PAUSED)
        _select_downloads_row(win, session_manager, record)

        win._shortcut_pause_resume.activated.emit()

        session_manager.resume_torrent.assert_called_once_with("abc123")
        session_manager.pause_torrent.assert_not_called()
    finally:
        win.close()


def test_delete_is_a_noop_with_a_multi_row_selection():
    # The table allows multi-select since bulk actions were added (see
    # DownloadsTab._build_multi_selection_context_menu) -- the single-target
    # Delete/Space shortcuts must not silently act on an arbitrary row out of
    # a multi-row selection. Note: QTableWidget.selectRow() REPLACES the
    # current selection rather than extending it (even in ExtendedSelection
    # mode) -- a real multi-row selection needs the selection model directly.
    win, session_manager, _ = _make_window()
    try:
        win._tabs.setCurrentWidget(win._downloads_tab)
        record_a = TorrentRecord(info_hash="a", name="A", state=TorrentState.DOWNLOADING)
        record_b = TorrentRecord(info_hash="b", name="B", state=TorrentState.DOWNLOADING)
        session_manager.get_record.side_effect = lambda ih: {"a": record_a, "b": record_b}.get(ih)
        win._downloads_tab._add_row(record_a)
        win._downloads_tab._add_row(record_b)
        table = win._downloads_tab.table
        selection_model = table.selectionModel()
        for row in (win._downloads_tab._rows["a"], win._downloads_tab._rows["b"]):
            selection_model.select(
                table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        assert win._downloads_tab.selected_info_hash() is None  # sanity: the selection really is multi-row

        win._shortcut_remove_torrent.activated.emit()
        session_manager.remove_torrent.assert_not_called()

        win._shortcut_pause_resume.activated.emit()
        session_manager.pause_torrent.assert_not_called()
        session_manager.resume_torrent.assert_not_called()
    finally:
        win.close()


def test_space_is_a_noop_when_downloads_tab_not_active():
    win, session_manager, _ = _make_window()
    try:
        record = TorrentRecord(info_hash="abc123", name="Foo", state=TorrentState.DOWNLOADING)
        _select_downloads_row(win, session_manager, record)
        win._tabs.setCurrentWidget(win._add_tab)

        win._shortcut_pause_resume.activated.emit()

        session_manager.pause_torrent.assert_not_called()
        session_manager.resume_torrent.assert_not_called()
    finally:
        win.close()


# --------------------------------------------------------------- status row


def test_status_row_reflects_counts_and_combined_rates():
    win, session_manager, _ = _make_window()
    try:
        records = [
            TorrentRecord(info_hash="a", state=TorrentState.DOWNLOADING, download_rate=1024, upload_rate=512),
            TorrentRecord(info_hash="b", state=TorrentState.SEEDING, download_rate=0, upload_rate=2048),
            TorrentRecord(info_hash="c", state=TorrentState.PAUSED, download_rate=0, upload_rate=0),
            TorrentRecord(info_hash="d", state=TorrentState.ERROR, download_rate=0, upload_rate=0),
        ]
        session_manager.all_records.return_value = records

        win._update_status_row()

        assert win._status_active_label.text() == tr("main_window.status_active", count=2)
        assert win._status_paused_label.text() == tr("main_window.status_paused", count=1)
        assert win._status_error_label.text() == tr("main_window.status_error", count=1)
        assert win._status_download_rate_label.text() == tr(
            "main_window.status_download_rate", rate=human_rate(1024)
        )
        assert win._status_upload_rate_label.text() == tr("main_window.status_upload_rate", rate=human_rate(2560))
    finally:
        win.close()


def test_status_row_updates_when_torrent_status_updated_signal_fires():
    win, session_manager, _ = _make_window()
    try:
        record = TorrentRecord(info_hash="a", state=TorrentState.DOWNLOADING, download_rate=100, upload_rate=0)
        session_manager.all_records.return_value = [record]

        win._on_status_row_update("a", record)

        assert win._status_active_label.text() == tr("main_window.status_active", count=1)
        assert win._status_download_rate_label.text() == tr("main_window.status_download_rate", rate=human_rate(100))
    finally:
        win.close()


def test_status_row_shows_dash_when_free_space_unavailable():
    win, session_manager, _ = _make_window()
    try:
        session_manager.all_records.return_value = []
        win._settings.default_download_dir = "Z:\\definitely\\does\\not\\exist\\path"

        win._update_status_row()

        assert win._status_free_space_label.text() == tr("main_window.status_free_space", free="—")
    finally:
        win.close()


# --------------------------------------------------------------- turtle mode


def test_turtle_mode_button_toggled_calls_scheduler():
    scheduler = MagicMock()
    win, _, _ = _make_window(bandwidth_scheduler=scheduler)
    try:
        win._turtle_mode_button.setChecked(True)
        scheduler.set_turtle_mode.assert_called_once_with(True)

        scheduler.set_turtle_mode.reset_mock()
        win._turtle_mode_button.setChecked(False)
        scheduler.set_turtle_mode.assert_called_once_with(False)
    finally:
        win.close()


def _make_scheduler(settings=None):
    session_manager = MagicMock()
    settings = settings or Settings()
    scheduler = BandwidthScheduler(session_manager, settings)
    scheduler._timer.stop()
    session_manager.set_rate_limits.reset_mock()
    return scheduler, session_manager


def test_set_turtle_mode_enabled_applies_default_turtle_values():
    scheduler, session_manager = _make_scheduler()

    scheduler.set_turtle_mode(True)

    session_manager.set_rate_limits.assert_called_once_with(50, 20)


def test_set_turtle_mode_enabled_applies_custom_turtle_values():
    scheduler, session_manager = _make_scheduler()

    scheduler.set_turtle_mode(True, turtle_download_kbps=10, turtle_upload_kbps=5)

    session_manager.set_rate_limits.assert_called_once_with(10, 5)


def test_set_turtle_mode_disabled_restores_base_settings_limits():
    settings = Settings()
    settings.download_rate_limit_kbps = 500
    settings.upload_rate_limit_kbps = 200
    scheduler, session_manager = _make_scheduler(settings=settings)

    scheduler.set_turtle_mode(True)
    session_manager.set_rate_limits.reset_mock()
    scheduler.set_turtle_mode(False)

    session_manager.set_rate_limits.assert_called_once_with(500, 200)


def test_turtle_mode_suppresses_schedule_reevaluation_while_active_but_tracks_state():
    settings = Settings()
    settings.bandwidth_schedule.enabled = True
    settings.bandwidth_schedule.start_hour = 8
    settings.bandwidth_schedule.end_hour = 22
    settings.bandwidth_schedule.limited_download_kbps = 30
    settings.bandwidth_schedule.limited_upload_kbps = 10

    with patch("torrent2000.engine.bandwidth_scheduler.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 1, 1, 10, 0, 0)  # inside the window
        scheduler, session_manager = _make_scheduler(settings=settings)
        scheduler.set_turtle_mode(True)
        session_manager.set_rate_limits.reset_mock()

        mock_datetime.now.return_value = datetime(2026, 1, 1, 23, 0, 0)  # a genuine state change, now outside
        scheduler.evaluate_now()

        # Turtle mode must swallow this re-evaluation entirely -- it must
        # not leak the schedule's own rate limits back onto the session.
        session_manager.set_rate_limits.assert_not_called()

    # But the schedule state was still tracked correctly underneath, so
    # disabling turtle mode afterwards restores *that* (unthrottled) value,
    # not a stale throttled one from before the window ended.
    scheduler.set_turtle_mode(False)
    session_manager.set_rate_limits.assert_called_once_with(
        settings.download_rate_limit_kbps, settings.upload_rate_limit_kbps
    )
