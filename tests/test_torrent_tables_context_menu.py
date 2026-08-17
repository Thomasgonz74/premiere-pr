"""Regression tests for the right-click context menu on downloads_tab.py and
share_tab.py (Pause/Resume, Remove, Recheck, Move storage) and for the
remove-button/context-menu remove action's three-way confirmation flow,
end to end through the actual widgets (Phase 2 audit finding)."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton

from torrent2000.config.settings import Settings
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState
from torrent2000.i18n.translator import tr
from torrent2000.ui.tabs.downloads_tab import ACTION_COLUMN, DownloadsTab
from torrent2000.ui.tabs.share_tab import ShareTab


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _action_by_text(menu, text):
    for action in menu.actions():
        if action.text() == text:
            return action
    raise AssertionError(f"No action with text {text!r}; menu has {[a.text() for a in menu.actions()]}")


def _patched_message_box(clicked_sentinel, addButton_sequence):
    mock_box_cls = MagicMock()
    box = mock_box_cls.return_value
    box.addButton.side_effect = addButton_sequence
    box.clickedButton.return_value = clicked_sentinel
    return mock_box_cls


# ------------------------------------------------------------- downloads_tab

def _downloads_tab_with_record(record):
    session_manager = MagicMock()
    session_manager.all_records.return_value = [record]
    session_manager.get_record.return_value = record
    return DownloadsTab(session_manager), session_manager


def test_downloads_tab_context_menu_pause_action_calls_pause_torrent():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING)
    tab, session_manager = _downloads_tab_with_record(record)

    menu = tab._build_context_menu("h1")
    _action_by_text(menu, tr("common.pause")).trigger()

    session_manager.pause_torrent.assert_called_once_with("h1")
    session_manager.resume_torrent.assert_not_called()


def test_downloads_tab_context_menu_shows_resume_when_paused():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.PAUSED)
    tab, session_manager = _downloads_tab_with_record(record)

    menu = tab._build_context_menu("h1")
    _action_by_text(menu, tr("common.resume")).trigger()

    session_manager.resume_torrent.assert_called_once_with("h1")
    session_manager.pause_torrent.assert_not_called()


def test_downloads_tab_context_menu_recheck_action_calls_recheck_torrent():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING)
    tab, session_manager = _downloads_tab_with_record(record)

    menu = tab._build_context_menu("h1")
    _action_by_text(menu, tr("common.context_recheck")).trigger()

    session_manager.recheck_torrent.assert_called_once_with("h1")


def test_downloads_tab_context_menu_move_storage_calls_move_storage_with_chosen_dir():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING)
    tab, session_manager = _downloads_tab_with_record(record)

    menu = tab._build_context_menu("h1")
    with patch.object(QFileDialog, "getExistingDirectory", return_value="D:/new/path"):
        _action_by_text(menu, tr("common.context_move_storage")).trigger()

    session_manager.move_storage.assert_called_once_with("h1", "D:/new/path")


def test_downloads_tab_context_menu_move_storage_no_op_when_dialog_cancelled():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING)
    tab, session_manager = _downloads_tab_with_record(record)

    menu = tab._build_context_menu("h1")
    with patch.object(QFileDialog, "getExistingDirectory", return_value=""):
        _action_by_text(menu, tr("common.context_move_storage")).trigger()

    session_manager.move_storage.assert_not_called()


def test_downloads_tab_context_menu_remove_action_removes_only_when_chosen():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING)
    tab, session_manager = _downloads_tab_with_record(record)

    menu = tab._build_context_menu("h1")
    remove_only = object()
    mock_box_cls = _patched_message_box(remove_only, [remove_only, object(), object()])
    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        _action_by_text(menu, tr("common.remove")).trigger()

    session_manager.remove_torrent.assert_called_once_with("h1")


def test_downloads_tab_context_menu_remove_action_deletes_files_when_chosen():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING)
    tab, session_manager = _downloads_tab_with_record(record)

    menu = tab._build_context_menu("h1")
    remove_with_files = object()
    mock_box_cls = _patched_message_box(remove_with_files, [object(), remove_with_files, object()])
    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        _action_by_text(menu, tr("common.remove")).trigger()

    session_manager.remove_torrent.assert_called_once_with("h1", delete_files=True)


def test_downloads_tab_context_menu_remove_action_cancel_removes_nothing():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING)
    tab, session_manager = _downloads_tab_with_record(record)

    menu = tab._build_context_menu("h1")
    cancel = object()
    mock_box_cls = _patched_message_box(cancel, [object(), object(), cancel])
    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        _action_by_text(menu, tr("common.remove")).trigger()

    session_manager.remove_torrent.assert_not_called()


def test_downloads_tab_remove_button_click_removes_only_when_chosen():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING)
    tab, session_manager = _downloads_tab_with_record(record)

    row = tab._rows["h1"]
    button = tab.table.cellWidget(row, ACTION_COLUMN)

    remove_only = object()
    mock_box_cls = _patched_message_box(remove_only, [remove_only, object(), object()])
    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        button.click()

    session_manager.remove_torrent.assert_called_once_with("h1")


def test_downloads_tab_remove_button_click_deletes_files_when_chosen():
    record = TorrentRecord(info_hash="h1", name="X", state=TorrentState.DOWNLOADING)
    tab, session_manager = _downloads_tab_with_record(record)

    row = tab._rows["h1"]
    button = tab.table.cellWidget(row, ACTION_COLUMN)

    remove_with_files = object()
    mock_box_cls = _patched_message_box(remove_with_files, [object(), remove_with_files, object()])
    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        button.click()

    session_manager.remove_torrent.assert_called_once_with("h1", delete_files=True)


# ----------------------------------------------------------------- share_tab

def _share_tab_with_record(record):
    session_manager = MagicMock()
    session_manager.get_record.return_value = record
    share_limit_service = MagicMock()
    share_limit_service.tracked_info_hashes.return_value = []
    tab = ShareTab(session_manager, share_limit_service, Settings())
    return tab, session_manager


def test_share_tab_context_menu_pause_action_calls_pause_torrent():
    record = TorrentRecord(info_hash="s1", name="X", state=TorrentState.SEEDING)
    tab, session_manager = _share_tab_with_record(record)

    menu = tab._build_context_menu("s1")
    _action_by_text(menu, tr("common.pause")).trigger()

    session_manager.pause_torrent.assert_called_once_with("s1")


def test_share_tab_context_menu_shows_resume_when_paused():
    record = TorrentRecord(info_hash="s1", name="X", state=TorrentState.PAUSED)
    tab, session_manager = _share_tab_with_record(record)

    menu = tab._build_context_menu("s1")
    _action_by_text(menu, tr("common.resume")).trigger()

    session_manager.resume_torrent.assert_called_once_with("s1")


def test_share_tab_context_menu_recheck_action_calls_recheck_torrent():
    record = TorrentRecord(info_hash="s1", name="X", state=TorrentState.SEEDING)
    tab, session_manager = _share_tab_with_record(record)

    menu = tab._build_context_menu("s1")
    _action_by_text(menu, tr("common.context_recheck")).trigger()

    session_manager.recheck_torrent.assert_called_once_with("s1")


def test_share_tab_context_menu_move_storage_calls_move_storage_with_chosen_dir():
    record = TorrentRecord(info_hash="s1", name="X", state=TorrentState.SEEDING)
    tab, session_manager = _share_tab_with_record(record)

    menu = tab._build_context_menu("s1")
    with patch.object(QFileDialog, "getExistingDirectory", return_value="D:/moved"):
        _action_by_text(menu, tr("common.context_move_storage")).trigger()

    session_manager.move_storage.assert_called_once_with("s1", "D:/moved")


def test_share_tab_context_menu_remove_action_deletes_files_when_chosen():
    record = TorrentRecord(info_hash="s1", name="X", state=TorrentState.SEEDING)
    tab, session_manager = _share_tab_with_record(record)

    menu = tab._build_context_menu("s1")
    remove_with_files = object()
    mock_box_cls = _patched_message_box(remove_with_files, [object(), remove_with_files, object()])
    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        _action_by_text(menu, tr("common.remove")).trigger()

    session_manager.remove_torrent.assert_called_once_with("s1", delete_files=True)


def test_share_tab_remove_button_click_deletes_files_when_chosen():
    record = TorrentRecord(info_hash="s1", name="X", state=TorrentState.SEEDING)
    session_manager = MagicMock()
    session_manager.get_record.return_value = record
    share_limit_service = MagicMock()
    share_limit_service.tracked_info_hashes.return_value = ["s1"]
    share_limit_service.limit_for.return_value = None
    share_limit_service.progress.return_value = (0.0, 0)

    tab = ShareTab(session_manager, share_limit_service, Settings())
    row = tab._rows["s1"]
    actions_widget = tab.table.cellWidget(row, 6)
    remove_button = next(b for b in actions_widget.findChildren(QPushButton) if b.objectName() == "dangerButton")

    remove_with_files = object()
    mock_box_cls = _patched_message_box(remove_with_files, [object(), remove_with_files, object()])
    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        remove_button.click()

    session_manager.remove_torrent.assert_called_once_with("s1", delete_files=True)


def test_downloads_and_share_tabs_have_custom_context_menu_policy():
    from PySide6.QtCore import Qt

    downloads_tab, _ = _downloads_tab_with_record(TorrentRecord(info_hash="h1", name="X"))
    assert downloads_tab.table.contextMenuPolicy() == Qt.CustomContextMenu

    share_tab, _ = _share_tab_with_record(TorrentRecord(info_hash="s1", name="X"))
    assert share_tab.table.contextMenuPolicy() == Qt.CustomContextMenu
