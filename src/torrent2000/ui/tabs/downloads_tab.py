from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState
from torrent2000.i18n.translator import tr
from torrent2000.ui.dialogs.file_priority_dialog import FilePriorityDialog
from torrent2000.ui.dialogs.peer_list_dialog import PeerListDialog
from torrent2000.ui.dialogs.speed_graph_dialog import SpeedGraphDialog
from torrent2000.ui.widgets.table_helpers import (
    confirm_and_remove,
    configure_no_stretch_table,
    info_hash_at,
    make_remove_button,
    reindex_rows_by_info_hash,
)
from torrent2000.ui.widgets.tetris_progress import TetrisProgressWidget
from torrent2000.ui.widgets.tracker_editor import TrackerEditorWidget
from torrent2000.utils.formatting import human_eta, human_rate

ACTION_COLUMN = 8

_STATE_LABEL_KEYS = {
    TorrentState.QUEUED: "downloads_tab.state_queued",
    TorrentState.CHECKING_METADATA: "downloads_tab.state_checking_metadata",
    TorrentState.AWAITING_ANALYSIS: "downloads_tab.state_awaiting_analysis",
    TorrentState.DOWNLOADING: "downloads_tab.state_downloading",
    TorrentState.PAUSED: "downloads_tab.state_paused",
    TorrentState.SEEDING: "downloads_tab.state_seeding",
    TorrentState.FINISHED: "downloads_tab.state_finished",
    TorrentState.ERROR: "downloads_tab.state_error",
}

# States where a health verdict wouldn't mean anything yet -- nothing is
# transferring, so peer/seed counts and tracker errors are simply not
# populated (or not relevant) yet.
_HEALTH_MEANINGLESS_STATES = {
    TorrentState.PAUSED,
    TorrentState.AWAITING_ANALYSIS,
    TorrentState.CHECKING_METADATA,
    TorrentState.QUEUED,
}

_HEALTH_TOOLTIP_KEYS = {
    "critical": "downloads_tab.health_critical_tooltip",
    "warning": "downloads_tab.health_warning_tooltip",
    "healthy": "downloads_tab.health_healthy_tooltip",
}

_HEALTH_COLORS = {
    "critical": QColor(255, 205, 205),
    "warning": QColor(255, 244, 180),
    "healthy": QColor(205, 245, 205),
}

_PRIVATE_BADGE_PREFIX = "\U0001f512 "  # lock emoji


def _columns() -> list[str]:
    return [
        tr("downloads_tab.column_name"),
        tr("downloads_tab.column_progress"),
        tr("downloads_tab.column_eta"),
        tr("downloads_tab.column_download_rate"),
        tr("downloads_tab.column_upload_rate"),
        tr("downloads_tab.column_peers"),
        tr("downloads_tab.column_state"),
        tr("downloads_tab.column_category"),
        tr("downloads_tab.column_action"),
    ]


def _state_label(state: TorrentState) -> str:
    return tr(_STATE_LABEL_KEYS.get(state, "downloads_tab.state_error"))


def _eta_text(record: TorrentRecord) -> str:
    if record.download_rate > 0 and record.progress < 1.0:
        remaining_bytes = record.total_size * (1 - record.progress)
        return human_eta(remaining_bytes / record.download_rate)
    return human_eta(None)


def _health_status(record: TorrentRecord) -> str:
    """Classifies torrent health from existing TorrentRecord fields alone:
    "critical" (errored, or no seeds while the tracker is erroring),
    "warning" (no peers or no seeds), "healthy", or "" when health isn't a
    meaningful concept yet for this state (see _HEALTH_MEANINGLESS_STATES)."""
    if record.state in _HEALTH_MEANINGLESS_STATES:
        return ""
    if record.state == TorrentState.ERROR:
        return "critical"
    has_tracker_error = any(tracker.last_error for tracker in record.trackers)
    if record.num_seeds == 0 and has_tracker_error:
        return "critical"
    if record.num_seeds == 0 or record.num_peers == 0:
        return "warning"
    return "healthy"


def _set_text_if_changed(item: QTableWidgetItem, text: str) -> None:
    if item.text() != text:
        item.setText(text)


def _set_tooltip_if_changed(item: QTableWidgetItem, tooltip: str) -> None:
    if item.toolTip() != tooltip:
        item.setToolTip(tooltip)


def _apply_health(item: QTableWidgetItem, record: TorrentRecord) -> None:
    status = _health_status(record)
    color = _HEALTH_COLORS.get(status)
    if color is not None:
        item.setBackground(color)
        _set_tooltip_if_changed(item, tr(_HEALTH_TOOLTIP_KEYS[status]))
    else:
        item.setData(Qt.BackgroundRole, None)
        _set_tooltip_if_changed(item, "")


def _name_text(record: TorrentRecord) -> str:
    base = record.name or record.info_hash[:12]
    return f"{_PRIVATE_BADGE_PREFIX}{base}" if record.is_private else base


def _name_tooltip(record: TorrentRecord) -> str:
    base = record.name or record.info_hash[:12]
    if record.is_private:
        return f"{base}\n\n{tr('downloads_tab.private_badge_tooltip')}"
    return base


class DownloadsTab(QWidget):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._rows: dict[str, int] = {}
        self._progress_widgets: dict[str, TetrisProgressWidget] = {}
        self._selected_info_hash: str | None = None
        self._current_record: TorrentRecord | None = None

        layout = QVBoxLayout(self)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(tr("common.search_placeholder"))
        self.search_input.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_input)

        splitter = QSplitter(Qt.Vertical, self)
        layout.addWidget(splitter)

        self.table = QTableWidget(0, 9, self)
        self.table.setHorizontalHeaderLabels(_columns())
        configure_no_stretch_table(self.table, 220)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu_requested)
        splitter.addWidget(self.table)

        self.details_box = QGroupBox(tr("downloads_tab.details_group"), self)
        details_layout = QVBoxLayout(self.details_box)

        self.tracker_label = QLabel(self.details_box)
        details_layout.addWidget(self.tracker_label)

        actions_row = QHBoxLayout()
        self.pause_button = QPushButton(tr("downloads_tab.pause"), self.details_box)
        self.pause_button.clicked.connect(self._on_pause_clicked)
        actions_row.addWidget(self.pause_button)
        self.resume_button = QPushButton(tr("downloads_tab.resume"), self.details_box)
        self.resume_button.clicked.connect(self._on_resume_clicked)
        actions_row.addWidget(self.resume_button)
        actions_row.addStretch(1)
        details_layout.addLayout(actions_row)

        priority_row = QHBoxLayout()
        self.queue_label = QLabel(self.details_box)
        priority_row.addWidget(self.queue_label)
        self.queue_up_button = QPushButton(tr("downloads_tab.queue_up"), self.details_box)
        self.queue_up_button.clicked.connect(self._on_queue_up_clicked)
        priority_row.addWidget(self.queue_up_button)
        self.queue_down_button = QPushButton(tr("downloads_tab.queue_down"), self.details_box)
        self.queue_down_button.clicked.connect(self._on_queue_down_clicked)
        priority_row.addWidget(self.queue_down_button)
        self.sequential_checkbox = QCheckBox(tr("downloads_tab.sequential"), self.details_box)
        self.sequential_checkbox.toggled.connect(self._on_sequential_toggled)
        priority_row.addWidget(self.sequential_checkbox)
        priority_row.addStretch(1)
        details_layout.addLayout(priority_row)

        self.tracker_editor = TrackerEditorWidget(self.details_box)
        details_layout.addWidget(self.tracker_editor)

        splitter.addWidget(self.details_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self._set_no_selection_labels()

        self._session_manager.torrent_added.connect(self._on_torrent_added)
        self._session_manager.torrent_removed.connect(self._on_torrent_removed)
        self._session_manager.torrent_status_updated.connect(self._on_status_updated)

        for record in self._session_manager.all_records():
            self._add_row(record)

    # ----------------------------------------------------------- retranslate

    def retranslate_ui(self) -> None:
        self.search_input.setPlaceholderText(tr("common.search_placeholder"))
        self.table.setHorizontalHeaderLabels(_columns())
        self.details_box.setTitle(tr("downloads_tab.details_group"))
        self.pause_button.setText(tr("downloads_tab.pause"))
        self.resume_button.setText(tr("downloads_tab.resume"))
        self.queue_up_button.setText(tr("downloads_tab.queue_up"))
        self.queue_down_button.setText(tr("downloads_tab.queue_down"))
        self.sequential_checkbox.setText(tr("downloads_tab.sequential"))
        self.tracker_editor.retranslate_ui()
        if self._current_record is not None:
            self._update_details(self._current_record)
        else:
            self._set_no_selection_labels()
        for info_hash, row in self._rows.items():
            record = self._session_manager.get_record(info_hash)
            if record is not None:
                self.table.item(row, 0).setToolTip(_name_tooltip(record))
                self.table.item(row, 6).setText(_state_label(record.state))
                _apply_health(self.table.item(row, 6), record)
        remove_label = tr("common.remove")
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, ACTION_COLUMN)
            if widget is not None:
                widget.setText(remove_label)

    def _set_no_selection_labels(self) -> None:
        self.tracker_label.setText(tr("downloads_tab.tracker_current", tracker="—"))
        self.queue_label.setText(tr("downloads_tab.queue_position", position="—"))

    # -------------------------------------------------------------- signals

    def _on_torrent_added(self, info_hash: str) -> None:
        record = self._session_manager.get_record(info_hash)
        if record is not None:
            self._add_row(record)

    def _on_torrent_removed(self, info_hash: str) -> None:
        row = self._rows.pop(info_hash, None)
        self._progress_widgets.pop(info_hash, None)
        if row is not None:
            self.table.removeRow(row)
            self._reindex_rows()
            self._apply_filter()
        if self._selected_info_hash == info_hash:
            self._selected_info_hash = None
            self._current_record = None
            self.tracker_editor.bind(self._session_manager, None)

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        row = self._rows.get(info_hash)
        if row is None:
            return
        _set_text_if_changed(self.table.item(row, 0), _name_text(record))
        _set_tooltip_if_changed(self.table.item(row, 0), _name_tooltip(record))
        tetris_widget = self._progress_widgets.get(info_hash)
        if tetris_widget is not None:
            tetris_widget.set_progress(record.progress)
        _set_text_if_changed(self.table.item(row, 2), _eta_text(record))
        _set_text_if_changed(self.table.item(row, 3), human_rate(record.download_rate))
        _set_text_if_changed(self.table.item(row, 4), human_rate(record.upload_rate))
        _set_text_if_changed(
            self.table.item(row, 5),
            tr("downloads_tab.peers_seeds", peers=record.num_peers, seeds=record.num_seeds),
        )
        _set_text_if_changed(self.table.item(row, 6), _state_label(record.state))
        _apply_health(self.table.item(row, 6), record)
        _set_text_if_changed(self.table.item(row, 7), record.category)

        if info_hash == self._selected_info_hash:
            self._update_details(record)

    # --------------------------------------------------------------- rows

    def _add_row(self, record: TorrentRecord) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[record.info_hash] = row

        self.table.setItem(row, 0, QTableWidgetItem(_name_text(record)))
        self.table.item(row, 0).setToolTip(_name_tooltip(record))
        tetris_widget = TetrisProgressWidget(parent=self.table)
        tetris_widget.set_progress(record.progress)
        self.table.setCellWidget(row, 1, tetris_widget)
        self.table.setRowHeight(row, max(self.table.rowHeight(row), tetris_widget.sizeHint().height() + 4))
        self._progress_widgets[record.info_hash] = tetris_widget
        self.table.setItem(row, 2, QTableWidgetItem(_eta_text(record)))
        self.table.setItem(row, 3, QTableWidgetItem(human_rate(record.download_rate)))
        self.table.setItem(row, 4, QTableWidgetItem(human_rate(record.upload_rate)))
        self.table.setItem(row, 5, QTableWidgetItem(tr("downloads_tab.peers_seeds", peers=record.num_peers, seeds=record.num_seeds)))
        self.table.setItem(row, 6, QTableWidgetItem(_state_label(record.state)))
        _apply_health(self.table.item(row, 6), record)
        self.table.setItem(row, 7, QTableWidgetItem(record.category))
        for col in (0, 2, 3, 4, 5, 6, 7):
            item = self.table.item(row, col)
            item.setData(Qt.UserRole, record.info_hash)

        remove_button = make_remove_button(
            self.table,
            lambda ih=record.info_hash: self._session_manager.remove_torrent(ih),
            lambda ih=record.info_hash: self._session_manager.remove_torrent(ih, delete_files=True),
        )
        self.table.setCellWidget(row, ACTION_COLUMN, remove_button)
        self._apply_filter()

    def _reindex_rows(self) -> None:
        reindex_rows_by_info_hash(self.table, self._rows)

    # ---------------------------------------------------------------- filter

    def _apply_filter(self, _text: str = "") -> None:
        query = self.search_input.text().strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            name = item.text().lower() if item is not None else ""
            self.table.setRowHidden(row, bool(query) and query not in name)

    # ------------------------------------------------------------ selection

    def _selected_rows(self) -> list[int]:
        return sorted({item.row() for item in self.table.selectedItems()})

    def _selected_info_hashes(self) -> list[str]:
        hashes = []
        for row in self._selected_rows():
            item = self.table.item(row, 0)
            info_hash = item.data(Qt.UserRole) if item is not None else None
            if info_hash:
                hashes.append(info_hash)
        return hashes

    def selected_info_hash(self) -> str | None:
        """The single selected torrent's info_hash, or None when zero or
        more than one row is selected -- used by MainWindow's global
        Delete/Space shortcuts, which (like the details panel) only ever
        target one torrent at a time. Bulk operations go through the
        context menu instead (see _build_multi_selection_context_menu),
        not through these single-target shortcuts."""
        return self._selected_info_hash

    def _on_selection_changed(self) -> None:
        rows = self._selected_rows()
        # A multi-row (or empty) selection has no single torrent to show
        # details for -- blank the panel rather than picking an arbitrary
        # row from the selection.
        if len(rows) != 1:
            self._selected_info_hash = None
            self._current_record = None
            self.tracker_editor.bind(self._session_manager, None)
            self._set_no_selection_labels()
            return
        hash_item = self.table.item(rows[0], 0)
        info_hash = hash_item.data(Qt.UserRole) if hash_item is not None else None
        if not info_hash:
            self._selected_info_hash = None
            self._current_record = None
            self.tracker_editor.bind(self._session_manager, None)
            self._set_no_selection_labels()
            return
        self._selected_info_hash = info_hash
        self.tracker_editor.bind(self._session_manager, info_hash)
        record = self._session_manager.get_record(info_hash)
        if record is not None:
            self._update_details(record)

    def _update_details(self, record: TorrentRecord) -> None:
        self._current_record = record
        self.tracker_label.setText(tr("downloads_tab.tracker_current", tracker=record.current_tracker or "—"))
        position = record.queue_position
        # libtorrent reports -1 once a torrent is actually active (not
        # waiting its turn) -- a meaningful position only exists while it's
        # still queued behind the active-torrent limit.
        queue_text = tr("downloads_tab.queue_position_value", position=position + 1) if position >= 0 else tr("downloads_tab.queue_position_active")
        self.queue_label.setText(tr("downloads_tab.queue_position", position=queue_text))
        self.sequential_checkbox.blockSignals(True)
        self.sequential_checkbox.setChecked(record.sequential_download)
        self.sequential_checkbox.blockSignals(False)

    # -------------------------------------------------------------- actions

    def _on_pause_clicked(self) -> None:
        if self._selected_info_hash:
            self._session_manager.pause_torrent(self._selected_info_hash)

    def _on_resume_clicked(self) -> None:
        if self._selected_info_hash:
            self._session_manager.resume_torrent(self._selected_info_hash)

    def _on_queue_up_clicked(self) -> None:
        if self._selected_info_hash:
            self._session_manager.move_queue_up(self._selected_info_hash)

    def _on_queue_down_clicked(self) -> None:
        if self._selected_info_hash:
            self._session_manager.move_queue_down(self._selected_info_hash)

    def _on_sequential_toggled(self, checked: bool) -> None:
        if self._selected_info_hash:
            self._session_manager.set_sequential_download(self._selected_info_hash, checked)

    # --------------------------------------------------------- context menu

    def _on_context_menu_requested(self, pos) -> None:
        info_hash = info_hash_at(self.table, pos)
        if not info_hash:
            return
        selected_hashes = self._selected_info_hashes()
        if len(selected_hashes) > 1:
            menu = self._build_multi_selection_context_menu(selected_hashes)
        else:
            menu = self._build_context_menu(info_hash)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _build_context_menu(self, info_hash: str) -> QMenu:
        record = self._session_manager.get_record(info_hash)
        menu = QMenu(self.table)
        if record is not None and record.state == TorrentState.PAUSED:
            resume_action = menu.addAction(tr("common.resume"))
            resume_action.triggered.connect(lambda: self._session_manager.resume_torrent(info_hash))
        else:
            pause_action = menu.addAction(tr("common.pause"))
            pause_action.triggered.connect(lambda: self._session_manager.pause_torrent(info_hash))
        recheck_action = menu.addAction(tr("common.context_recheck"))
        recheck_action.triggered.connect(lambda: self._session_manager.recheck_torrent(info_hash))
        move_action = menu.addAction(tr("common.context_move_storage"))
        move_action.triggered.connect(lambda: self._on_move_storage_requested(info_hash))
        menu.addSeparator()
        category_action = menu.addAction(tr("common.context_assign_category"))
        category_action.triggered.connect(lambda: self._on_assign_category_requested(info_hash))
        magnet_action = menu.addAction(tr("common.context_copy_magnet"))
        magnet_action.triggered.connect(lambda: self._on_copy_magnet_requested(info_hash))
        files_action = menu.addAction(tr("common.context_edit_files"))
        files_action.triggered.connect(lambda: self._on_edit_files_requested(info_hash))
        peers_action = menu.addAction(tr("common.context_view_peers"))
        peers_action.triggered.connect(lambda: self._on_view_peers_requested(info_hash))
        speed_action = menu.addAction(tr("common.context_view_speed_graph"))
        speed_action.triggered.connect(lambda: self._on_view_speed_graph_requested(info_hash))
        menu.addSeparator()
        remove_action = menu.addAction(tr("common.remove"))
        remove_action.triggered.connect(
            lambda: confirm_and_remove(
                self.table,
                lambda: self._session_manager.remove_torrent(info_hash),
                lambda: self._session_manager.remove_torrent(info_hash, delete_files=True),
            )
        )
        return menu

    def _build_multi_selection_context_menu(self, info_hashes: list[str]) -> QMenu:
        menu = QMenu(self.table)
        pause_action = menu.addAction(tr("common.context_pause_selection"))
        pause_action.triggered.connect(lambda: self._pause_selection(info_hashes))
        resume_action = menu.addAction(tr("common.context_resume_selection"))
        resume_action.triggered.connect(lambda: self._resume_selection(info_hashes))
        menu.addSeparator()
        remove_action = menu.addAction(tr("common.context_remove_selection"))
        remove_action.triggered.connect(lambda: self._remove_selection(info_hashes))
        return menu

    def _pause_selection(self, info_hashes: list[str]) -> None:
        for info_hash in info_hashes:
            self._session_manager.pause_torrent(info_hash)

    def _resume_selection(self, info_hashes: list[str]) -> None:
        for info_hash in info_hashes:
            self._session_manager.resume_torrent(info_hash)

    def _remove_selection(self, info_hashes: list[str]) -> None:
        # A single confirmation for the whole selection, not one per torrent
        # -- the callbacks themselves loop over every selected info_hash.
        confirm_and_remove(
            self.table,
            lambda: self._remove_many(info_hashes, delete_files=False),
            lambda: self._remove_many(info_hashes, delete_files=True),
        )

    def _remove_many(self, info_hashes: list[str], delete_files: bool) -> None:
        for info_hash in info_hashes:
            self._session_manager.remove_torrent(info_hash, delete_files=delete_files)

    def _on_move_storage_requested(self, info_hash: str) -> None:
        new_dir = QFileDialog.getExistingDirectory(self, tr("common.move_storage_dialog_title"))
        if new_dir:
            self._session_manager.move_storage(info_hash, new_dir)

    def _on_assign_category_requested(self, info_hash: str) -> None:
        record = self._session_manager.get_record(info_hash)
        current = record.category if record is not None else ""
        items = [c for c in self._session_manager.list_categories() if c]
        if current and current not in items:
            items.insert(0, current)
        if not items:
            items = [""]
        current_index = items.index(current) if current in items else 0
        category, ok = QInputDialog.getItem(
            self,
            tr("downloads_tab.category_dialog_title"),
            tr("downloads_tab.category_dialog_label"),
            items,
            current_index,
            True,
        )
        if ok:
            self._session_manager.set_torrent_category(info_hash, category.strip())

    def _on_copy_magnet_requested(self, info_hash: str) -> None:
        uri = self._session_manager.get_magnet_uri(info_hash)
        if uri:
            QApplication.clipboard().setText(uri)
        else:
            QMessageBox.information(
                self,
                tr("downloads_tab.magnet_not_available_title"),
                tr("downloads_tab.magnet_not_available_message"),
            )

    def _on_edit_files_requested(self, info_hash: str) -> None:
        FilePriorityDialog(self._session_manager, info_hash, self).exec()

    def _on_view_peers_requested(self, info_hash: str) -> None:
        PeerListDialog(self._session_manager, info_hash, self).show()

    def _on_view_speed_graph_requested(self, info_hash: str) -> None:
        SpeedGraphDialog(self._session_manager, info_hash, self).show()
