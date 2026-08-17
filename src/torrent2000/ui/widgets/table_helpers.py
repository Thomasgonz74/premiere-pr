"""Shared helpers for the torrent tables in downloads_tab.py, share_tab.py,
and rss_tab.py -- column setup, info_hash-to-row bookkeeping, the context-menu
click-to-info_hash lookup, and the "Remove" (with its remove-confirmation
dialog) button factory they'd otherwise each hand-roll independently.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QPushButton, QTableWidget, QWidget

from torrent2000.i18n.translator import tr


def configure_no_stretch_table(table: QTableWidget, first_column_width: int) -> None:
    """Deliberately NOT QHeaderView.Stretch: a Stretch column keeps total
    header width pinned to the viewport, so resizing any OTHER column
    silently shrinks/grows this one to compensate -- from the user's side,
    dragging a column border elsewhere makes THIS column's border move
    instead, while the one actually dragged snaps back to where it started.
    A fixed initial width with plain Interactive resizing (the default)
    makes every column resize independently."""
    table.setColumnWidth(0, first_column_width)
    table.verticalHeader().setVisible(False)


def reindex_rows_by_info_hash(table: QTableWidget, rows: dict[str, int]) -> None:
    """Rebuilds `rows` (info_hash -> row index) from column 0's UserRole
    data. Needed after Qt's removeRow() silently shifts every row below the
    removed one up by one, with no per-row signal to patch the mapping
    incrementally."""
    rows.clear()
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is None:
            continue
        info_hash = item.data(Qt.UserRole)
        if info_hash:
            rows[info_hash] = row


def info_hash_at(table: QTableWidget, pos) -> str | None:
    """Resolves a context-menu click position to the row's info_hash,
    always going through column 0's item (where every table keeps it in
    Qt.UserRole) regardless of which column was actually under the cursor --
    not every column's item carries that data itself."""
    item = table.itemAt(pos)
    if item is None:
        return None
    hash_item = table.item(item.row(), 0)
    if hash_item is None:
        return None
    return hash_item.data(Qt.UserRole)


def confirm_and_remove(
    parent: QWidget,
    on_click: Callable[[], None],
    on_click_with_files: Callable[[], None] | None = None,
) -> None:
    """Confirms before actually removing a torrent/subscription. With
    on_click_with_files (downloads/share tables, where the underlying data
    lives on disk), offers a third "remove and delete files" choice via
    custom-labeled buttons (same addButton(..., role) pattern already used
    for onboarding_dialog.py/main_window.py's update dialogs). Without it
    (RSS subscriptions -- no "files" concept), a plain Yes/No confirm."""
    if on_click_with_files is not None:
        box = QMessageBox(parent)
        box.setWindowTitle(tr("common.remove_confirm_title"))
        box.setText(tr("common.remove_confirm_message"))
        remove_only_button = box.addButton(tr("common.remove_only_button"), QMessageBox.AcceptRole)
        remove_with_files_button = box.addButton(tr("common.remove_with_files_button"), QMessageBox.DestructiveRole)
        box.addButton(tr("common.cancel"), QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is remove_only_button:
            on_click()
        elif clicked is remove_with_files_button:
            on_click_with_files()
    else:
        reply = QMessageBox.question(
            parent,
            tr("common.remove_confirm_title"),
            tr("common.remove_confirm_message"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            on_click()


def make_remove_button(
    parent: QWidget,
    on_click: Callable[[], None],
    on_click_with_files: Callable[[], None] | None = None,
) -> QPushButton:
    button = QPushButton(tr("common.remove"), parent)
    button.setObjectName("dangerButton")
    button.clicked.connect(lambda checked=False: confirm_and_remove(parent, on_click, on_click_with_files))
    return button
