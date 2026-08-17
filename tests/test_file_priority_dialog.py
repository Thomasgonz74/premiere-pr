import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from torrent2000.danger_scanner.models import FileEntry
from torrent2000.ui.dialogs.file_priority_dialog import FilePriorityDialog

INFO_HASH = "abc123"

FILES = [
    FileEntry(index=0, path="movie.mkv", size=1_000_000),
    FileEntry(index=1, path="subs/movie.srt", size=1_000),
    FileEntry(index=2, path="sample.mkv", size=50_000),
]


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def session_manager():
    sm = MagicMock()
    sm.get_torrent_files.return_value = FILES
    return sm


@pytest.fixture
def dialog(session_manager):
    return FilePriorityDialog(session_manager, INFO_HASH)


def test_dialog_lists_every_file_pre_checked(dialog):
    assert dialog.tree.topLevelItemCount() == len(FILES)
    for i, entry in enumerate(FILES):
        item = dialog.tree.topLevelItem(i)
        assert item.text(0) == entry.path
        assert item.data(0, Qt.UserRole) == entry.index
        assert item.checkState(0) == Qt.Checked
    assert dialog._excluded_indices() == set()


def test_uncheck_all_then_check_all_round_trips(dialog):
    dialog._uncheck_all()
    assert dialog._excluded_indices() == {0, 1, 2}

    dialog._check_all()
    assert dialog._excluded_indices() == set()


def test_save_calls_set_file_priorities_with_excluded_indices_and_closes(dialog, session_manager):
    dialog.tree.topLevelItem(1).setCheckState(0, Qt.Unchecked)
    dialog.tree.topLevelItem(2).setCheckState(0, Qt.Unchecked)

    dialog._on_save_clicked()

    session_manager.set_file_priorities.assert_called_once_with(INFO_HASH, {1, 2})
    assert dialog.result() == FilePriorityDialog.Accepted


def test_cancel_does_not_call_set_file_priorities(dialog, session_manager):
    dialog.tree.topLevelItem(0).setCheckState(0, Qt.Unchecked)

    dialog.reject()

    session_manager.set_file_priorities.assert_not_called()
    assert dialog.result() == FilePriorityDialog.Rejected


def test_no_metadata_yet_disables_the_tree_and_save_button(session_manager):
    session_manager.get_torrent_files.return_value = []

    d = FilePriorityDialog(session_manager, INFO_HASH)

    assert d.tree.topLevelItemCount() == 0
    # isVisible() would need the (never-shown) dialog itself to be shown --
    # isHidden() reflects the explicit setVisible() call regardless of that.
    assert not d.info_label.isHidden()
    assert not d.save_button.isEnabled()


def test_single_file_torrent_shows_the_warning_label(session_manager):
    session_manager.get_torrent_files.return_value = [FILES[0]]

    d = FilePriorityDialog(session_manager, INFO_HASH)

    assert d.tree.topLevelItemCount() == 1
    assert not d.info_label.isHidden()
    assert d.save_button.isEnabled()
