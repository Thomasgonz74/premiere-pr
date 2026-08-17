"""Regression tests for table_helpers.py: the remove-confirmation dialog
(confirm_and_remove / make_remove_button's new "remove and delete files"
choice) and info_hash_at's context-menu click-to-row resolution
(Phase 2 audit finding)."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidget, QTableWidgetItem

from torrent2000.ui.widgets.table_helpers import confirm_and_remove, info_hash_at, make_remove_button


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# --------------------------------------------------------- confirm_and_remove

def test_confirm_and_remove_remove_only_calls_on_click():
    on_click = MagicMock()
    on_click_with_files = MagicMock()
    remove_only = object()

    mock_box_cls = MagicMock()
    box = mock_box_cls.return_value
    box.addButton.side_effect = [remove_only, object(), object()]
    box.clickedButton.return_value = remove_only

    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        confirm_and_remove(None, on_click, on_click_with_files)

    on_click.assert_called_once()
    on_click_with_files.assert_not_called()


def test_confirm_and_remove_remove_with_files_calls_on_click_with_files():
    on_click = MagicMock()
    on_click_with_files = MagicMock()
    remove_with_files = object()

    mock_box_cls = MagicMock()
    box = mock_box_cls.return_value
    box.addButton.side_effect = [object(), remove_with_files, object()]
    box.clickedButton.return_value = remove_with_files

    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        confirm_and_remove(None, on_click, on_click_with_files)

    on_click.assert_not_called()
    on_click_with_files.assert_called_once()


def test_confirm_and_remove_cancel_calls_neither_callback():
    on_click = MagicMock()
    on_click_with_files = MagicMock()
    cancel = object()

    mock_box_cls = MagicMock()
    box = mock_box_cls.return_value
    box.addButton.side_effect = [object(), object(), cancel]
    box.clickedButton.return_value = cancel

    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        confirm_and_remove(None, on_click, on_click_with_files)

    on_click.assert_not_called()
    on_click_with_files.assert_not_called()


def test_confirm_and_remove_uses_three_custom_labeled_buttons():
    """Buttons must be added with the app's own French-first tr() labels,
    matching the addButton(text, role) pattern already used elsewhere
    (onboarding_dialog.py / main_window.py's update dialogs) -- not the
    QMessageBox built-in Yes/No/Cancel."""
    on_click = MagicMock()
    on_click_with_files = MagicMock()

    mock_box_cls = MagicMock()
    box = mock_box_cls.return_value
    box.addButton.side_effect = [object(), object(), object()]
    box.clickedButton.return_value = None

    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        confirm_and_remove(None, on_click, on_click_with_files)

    assert box.addButton.call_count == 3
    labels = [call.args[0] for call in box.addButton.call_args_list]
    assert labels == ["Retirer seulement", "Retirer et supprimer les fichiers", "Annuler"]


def test_confirm_and_remove_without_files_callback_uses_yes_no_dialog():
    on_click = MagicMock()

    mock_box_cls = MagicMock()
    mock_box_cls.Yes = QMessageBox.Yes
    mock_box_cls.No = QMessageBox.No
    mock_box_cls.question.return_value = QMessageBox.Yes

    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        confirm_and_remove(None, on_click)

    on_click.assert_called_once()
    mock_box_cls.question.assert_called_once()


def test_confirm_and_remove_without_files_callback_no_answer_skips_on_click():
    on_click = MagicMock()

    mock_box_cls = MagicMock()
    mock_box_cls.Yes = QMessageBox.Yes
    mock_box_cls.No = QMessageBox.No
    mock_box_cls.question.return_value = QMessageBox.No

    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        confirm_and_remove(None, on_click)

    on_click.assert_not_called()


# ---------------------------------------------------------- make_remove_button

def test_make_remove_button_click_goes_through_confirm_and_remove():
    on_click = MagicMock()
    on_click_with_files = MagicMock()
    remove_only = object()

    mock_box_cls = MagicMock()
    box = mock_box_cls.return_value
    box.addButton.side_effect = [remove_only, object(), object()]
    box.clickedButton.return_value = remove_only

    button = make_remove_button(None, on_click, on_click_with_files)
    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        button.click()

    on_click.assert_called_once()
    on_click_with_files.assert_not_called()


def test_make_remove_button_without_files_callback_shows_simple_confirm():
    """rss_tab.py's call site (single callback, unchanged) -- confirms the
    new default behavior is a plain Yes/No, not a crash and not a silent
    no-confirm removal."""
    on_click = MagicMock()

    mock_box_cls = MagicMock()
    mock_box_cls.Yes = QMessageBox.Yes
    mock_box_cls.No = QMessageBox.No
    mock_box_cls.question.return_value = QMessageBox.Yes

    button = make_remove_button(None, on_click)
    with patch("torrent2000.ui.widgets.table_helpers.QMessageBox", mock_box_cls):
        button.click()

    on_click.assert_called_once()


# -------------------------------------------------------------- info_hash_at

def test_info_hash_at_resolves_via_column_zero_item_regardless_of_click_column():
    table = QTableWidget(1, 3)
    item0 = QTableWidgetItem("name")
    item0.setData(Qt.UserRole, "hash123")
    table.setItem(0, 0, item0)
    table.setItem(0, 1, QTableWidgetItem("rate"))  # no UserRole set on this one
    table.resizeColumnsToContents()

    pos_col1 = table.visualRect(table.model().index(0, 1)).center()

    assert info_hash_at(table, pos_col1) == "hash123"


def test_info_hash_at_returns_none_when_no_item_at_position():
    table = QTableWidget(1, 3)
    table.setItem(0, 0, QTableWidgetItem("name"))

    assert info_hash_at(table, QPoint(-50, -50)) is None


def test_info_hash_at_returns_none_when_column_zero_item_has_no_hash():
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("name"))  # UserRole never set
    table.resizeColumnsToContents()

    pos = table.visualRect(table.model().index(0, 0)).center()

    assert info_hash_at(table, pos) is None
