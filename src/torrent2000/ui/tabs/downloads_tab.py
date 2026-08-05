from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
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
from torrent2000.ui.widgets.tetris_progress import TetrisProgressWidget
from torrent2000.ui.widgets.tracker_editor import TrackerEditorWidget
from torrent2000.utils.formatting import human_eta, human_rate, human_size

ACTION_COLUMN = 6

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


def _columns() -> list[str]:
    return [
        tr("downloads_tab.column_name"),
        tr("downloads_tab.column_progress"),
        tr("downloads_tab.column_download_rate"),
        tr("downloads_tab.column_upload_rate"),
        tr("downloads_tab.column_peers"),
        tr("downloads_tab.column_state"),
        tr("downloads_tab.column_action"),
    ]


def _state_label(state: TorrentState) -> str:
    return tr(_STATE_LABEL_KEYS.get(state, "downloads_tab.state_error"))


class DownloadsTab(QWidget):
    def __init__(self, session_manager: SessionManager, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._rows: dict[str, int] = {}
        self._progress_widgets: dict[str, TetrisProgressWidget] = {}
        self._selected_info_hash: str | None = None
        self._current_record: TorrentRecord | None = None

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical, self)
        layout.addWidget(splitter)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(_columns())
        # Deliberately NOT QHeaderView.Stretch: a Stretch column keeps total
        # header width pinned to the viewport, so resizing any OTHER column
        # silently shrinks/grows this one to compensate -- from the user's
        # side, dragging a column border elsewhere makes THIS column's
        # border move instead, while the one actually dragged snaps back
        # to where it started. A fixed initial width with plain Interactive
        # resizing (the default) makes every column resize independently.
        self.table.setColumnWidth(0, 220)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
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
                self.table.item(row, 5).setText(_state_label(record.state))
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
        if self._selected_info_hash == info_hash:
            self._selected_info_hash = None
            self._current_record = None
            self.tracker_editor.bind(self._session_manager, None)

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        row = self._rows.get(info_hash)
        if row is None:
            return
        self.table.item(row, 0).setText(record.name or info_hash[:12])
        tetris_widget = self._progress_widgets.get(info_hash)
        if tetris_widget is not None:
            tetris_widget.set_progress(record.progress)
        self.table.item(row, 2).setText(human_rate(record.download_rate))
        self.table.item(row, 3).setText(human_rate(record.upload_rate))
        self.table.item(row, 4).setText(tr("downloads_tab.peers_seeds", peers=record.num_peers, seeds=record.num_seeds))
        self.table.item(row, 5).setText(_state_label(record.state))

        if info_hash == self._selected_info_hash:
            self._update_details(record)

    # --------------------------------------------------------------- rows

    def _add_row(self, record: TorrentRecord) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[record.info_hash] = row

        self.table.setItem(row, 0, QTableWidgetItem(record.name or record.info_hash[:12]))
        tetris_widget = TetrisProgressWidget(parent=self.table)
        tetris_widget.set_progress(record.progress)
        self.table.setCellWidget(row, 1, tetris_widget)
        self.table.setRowHeight(row, max(self.table.rowHeight(row), tetris_widget.sizeHint().height() + 4))
        self._progress_widgets[record.info_hash] = tetris_widget
        self.table.setItem(row, 2, QTableWidgetItem(human_rate(record.download_rate)))
        self.table.setItem(row, 3, QTableWidgetItem(human_rate(record.upload_rate)))
        self.table.setItem(row, 4, QTableWidgetItem(tr("downloads_tab.peers_seeds", peers=record.num_peers, seeds=record.num_seeds)))
        self.table.setItem(row, 5, QTableWidgetItem(_state_label(record.state)))
        for col in (0, 2, 3, 4, 5):
            item = self.table.item(row, col)
            item.setData(Qt.UserRole, record.info_hash)

        remove_button = QPushButton(tr("common.remove"), self.table)
        remove_button.setObjectName("dangerButton")
        remove_button.clicked.connect(
            lambda checked=False, ih=record.info_hash: self._session_manager.remove_torrent(ih)
        )
        self.table.setCellWidget(row, ACTION_COLUMN, remove_button)

    def _reindex_rows(self) -> None:
        self._rows.clear()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                info_hash = item.data(Qt.UserRole)
                self._rows[info_hash] = row

    # ------------------------------------------------------------ selection

    def _on_selection_changed(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            self._selected_info_hash = None
            self._current_record = None
            self.tracker_editor.bind(self._session_manager, None)
            self._set_no_selection_labels()
            return
        info_hash = selected[0].data(Qt.UserRole)
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
