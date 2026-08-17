from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.share_limits import ShareLimitService
from torrent2000.engine.torrent_item import TorrentRecord, TorrentState
from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.drop_zone import DropZoneWidget
from torrent2000.ui.widgets.table_helpers import (
    confirm_and_remove,
    configure_no_stretch_table,
    info_hash_at,
    make_remove_button,
    reindex_rows_by_info_hash,
)
from torrent2000.utils.formatting import human_eta, human_rate, human_size

_STATE_LABEL_KEYS = {
    TorrentState.SEEDING: "share_tab.state_seeding",
    TorrentState.PAUSED: "share_tab.state_paused",
    TorrentState.QUEUED: "share_tab.state_queued",
    TorrentState.CHECKING_METADATA: "share_tab.state_checking",
    TorrentState.ERROR: "share_tab.state_error",
}

_LIMIT_REASON_KEYS = {
    "time": "share_tab.limit_reason_time",
    "data": "share_tab.limit_reason_data",
    "ratio": "share_tab.limit_reason_ratio",
}


def _columns() -> list[str]:
    return [
        tr("share_tab.column_name"),
        tr("share_tab.column_upload_rate"),
        tr("share_tab.column_uploaded_session"),
        tr("share_tab.column_time"),
        tr("share_tab.column_data"),
        tr("share_tab.column_state"),
        tr("share_tab.column_action"),
    ]


def _state_label(state: TorrentState) -> str:
    return tr(_STATE_LABEL_KEYS.get(state, "share_tab.state_error"))


def _limit_reason_label(reason: str) -> str:
    return tr(_LIMIT_REASON_KEYS.get(reason, "share_tab.limit_reached"))


class ShareTab(QWidget):
    """Dedicated seeding workspace: drop a torrent whose data you already
    have on disk here to share it with peers (this is what legitimately
    builds ratio -- real uploads to real peers), with optional caps on how
    long or how much to upload before automatically pausing."""

    def __init__(
        self, session_manager: SessionManager, share_limit_service: ShareLimitService, settings: Settings, parent=None
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._share_limit_service = share_limit_service
        self._settings = settings
        self._torrent_path: str | None = None
        self._rows: dict[str, int] = {}
        self._filter_text: str = ""

        layout = QVBoxLayout(self)

        self.source_box = QGroupBox(tr("share_tab.add_share_group"), self)
        source_layout = QVBoxLayout(self.source_box)

        self.drop_zone = DropZoneWidget(self.source_box)
        self.drop_zone.torrent_file_dropped.connect(self._on_torrent_file_selected)
        source_layout.addWidget(self.drop_zone)

        browse_row = QHBoxLayout()
        self.browse_button = QPushButton(tr("share_tab.browse_torrent"), self.source_box)
        self.browse_button.clicked.connect(self._on_browse_clicked)
        browse_row.addWidget(self.browse_button)
        self.selected_file_label = QLabel("", self.source_box)
        browse_row.addWidget(self.selected_file_label, 1)
        source_layout.addLayout(browse_row)

        magnet_row = QHBoxLayout()
        self.magnet_label = QLabel(tr("share_tab.magnet_label"), self.source_box)
        magnet_row.addWidget(self.magnet_label)
        self.magnet_input = QLineEdit(self.source_box)
        self.magnet_input.setPlaceholderText("magnet:?xt=urn:btih:...")
        magnet_row.addWidget(self.magnet_input, 1)
        source_layout.addLayout(magnet_row)

        data_row = QHBoxLayout()
        self.data_dir_label = QLabel(tr("share_tab.data_dir_label"), self.source_box)
        data_row.addWidget(self.data_dir_label)
        # Pre-filled with the default download directory: torrents added
        # normally (via the Add tab) land there, so a user who leaves them in
        # place to seed doesn't have to retype this path every time -- they
        # only need to change it for a torrent whose data actually lives
        # somewhere else.
        self.data_dir_input = QLineEdit(settings.default_download_dir, self.source_box)
        data_row.addWidget(self.data_dir_input, 1)
        self.data_browse_button = QPushButton(tr("common.browse"), self.source_box)
        self.data_browse_button.clicked.connect(self._on_browse_data_dir)
        data_row.addWidget(self.data_browse_button)
        source_layout.addLayout(data_row)

        limits_row = QHBoxLayout()
        self.time_limit_label = QLabel(tr("share_tab.time_limit_label"), self.source_box)
        limits_row.addWidget(self.time_limit_label)
        self.time_limit_spin = QSpinBox(self.source_box)
        self.time_limit_spin.setRange(0, 999)
        self.time_limit_spin.setSuffix(tr("share_tab.time_limit_suffix"))
        limits_row.addWidget(self.time_limit_spin)
        limits_row.addSpacing(16)
        self.data_limit_label = QLabel(tr("share_tab.data_limit_label"), self.source_box)
        limits_row.addWidget(self.data_limit_label)
        self.data_limit_spin = QSpinBox(self.source_box)
        self.data_limit_spin.setRange(0, 1_000_000)
        self.data_limit_spin.setSuffix(tr("share_tab.data_limit_suffix"))
        limits_row.addWidget(self.data_limit_spin)
        limits_row.addSpacing(16)
        self.ratio_limit_label = QLabel(tr("share_tab.ratio_limit_label"), self.source_box)
        limits_row.addWidget(self.ratio_limit_label)
        self.ratio_limit_spin = QDoubleSpinBox(self.source_box)
        self.ratio_limit_spin.setRange(0, 100)
        self.ratio_limit_spin.setSingleStep(0.1)
        self.ratio_limit_spin.setDecimals(1)
        self.ratio_limit_spin.setSuffix(tr("share_tab.ratio_limit_suffix"))
        limits_row.addWidget(self.ratio_limit_spin)
        limits_row.addStretch(1)
        source_layout.addLayout(limits_row)

        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.start_button = QPushButton(tr("share_tab.start_button"), self.source_box)
        self.start_button.clicked.connect(self._on_start_clicked)
        start_row.addWidget(self.start_button)
        source_layout.addLayout(start_row)

        layout.addWidget(self.source_box)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(tr("common.search_placeholder"))
        self.search_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self.search_input)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(_columns())
        configure_no_stretch_table(self.table, 220)
        # The Action column holds TWO buttons (Pause/Resume + Remove), unlike
        # every other table's single-button Action column -- left at the
        # default ~100px Interactive width, Qt forces both buttons to
        # squeeze into that regardless of their actual text, clipping it.
        # ResizeToContents re-measures from the cell widget's real sizeHint,
        # including after retranslate_ui() swaps in a longer/shorter locale.
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu_requested)
        layout.addWidget(self.table, 1)

        self._session_manager.torrent_status_updated.connect(self._on_status_updated)
        self._session_manager.torrent_removed.connect(self._on_torrent_removed)
        self._share_limit_service.limit_reached.connect(self._on_limit_reached)

        # ShareLimitService restores which torrents were being tracked for
        # sharing from disk in its own __init__ (run before this one, since
        # it's constructed first in app.py) -- populate the table with those
        # right away rather than waiting for the next torrent_status_updated
        # tick, matching how DownloadsTab already does this for all_records().
        for info_hash in self._share_limit_service.tracked_info_hashes():
            record = self._session_manager.get_record(info_hash)
            if record is not None:
                self._add_row(info_hash, record)
                self._update_row(self._rows[info_hash], info_hash, record)

    # ----------------------------------------------------------- retranslate

    def retranslate_ui(self) -> None:
        self.source_box.setTitle(tr("share_tab.add_share_group"))
        self.drop_zone.retranslate_ui()
        self.browse_button.setText(tr("share_tab.browse_torrent"))
        self.magnet_label.setText(tr("share_tab.magnet_label"))
        self.data_dir_label.setText(tr("share_tab.data_dir_label"))
        self.data_browse_button.setText(tr("common.browse"))
        self.time_limit_label.setText(tr("share_tab.time_limit_label"))
        self.time_limit_spin.setSuffix(tr("share_tab.time_limit_suffix"))
        self.data_limit_label.setText(tr("share_tab.data_limit_label"))
        self.data_limit_spin.setSuffix(tr("share_tab.data_limit_suffix"))
        self.ratio_limit_label.setText(tr("share_tab.ratio_limit_label"))
        self.ratio_limit_spin.setSuffix(tr("share_tab.ratio_limit_suffix"))
        self.start_button.setText(tr("share_tab.start_button"))
        self.search_input.setPlaceholderText(tr("common.search_placeholder"))
        self.table.setHorizontalHeaderLabels(_columns())
        for info_hash, row in self._rows.items():
            record = self._session_manager.get_record(info_hash)
            if record is not None:
                self._update_row(row, info_hash, record)

    # ---------------------------------------------------------------- source

    def _on_browse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("share_tab.choose_torrent_title"), "", "Torrent (*.torrent)")
        if path:
            self._on_torrent_file_selected(path)

    def _on_torrent_file_selected(self, path: str) -> None:
        self._torrent_path = path
        self.selected_file_label.setText(path)
        self.magnet_input.clear()

    def _on_browse_data_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("share_tab.choose_data_dir_title"), self.data_dir_input.text())
        if directory:
            self.data_dir_input.setText(directory)

    # ------------------------------------------------------------------ start

    def _on_start_clicked(self) -> None:
        data_dir = self.data_dir_input.text().strip()
        if not data_dir:
            QMessageBox.warning(self, tr("share_tab.missing_dir_title"), tr("share_tab.missing_dir_message"))
            return

        time_limit = self.time_limit_spin.value() * 3600 or None
        data_limit = self.data_limit_spin.value() * 1024 * 1024 or None
        ratio_limit = self.ratio_limit_spin.value() or None

        if self._torrent_path:
            info_hash = self._session_manager.add_torrent_from_file(self._torrent_path, data_dir)
        else:
            magnet_uri = self.magnet_input.text().strip()
            if not magnet_uri:
                QMessageBox.information(self, tr("share_tab.no_source_title"), tr("share_tab.no_source_message"))
                return
            info_hash = self._session_manager.add_torrent_from_magnet(magnet_uri, data_dir)
            self._session_manager.start_after_analysis(info_hash)

        self._share_limit_service.track(info_hash, time_limit, data_limit, ratio_limit=ratio_limit)
        self._reset_form()

    def _reset_form(self) -> None:
        self._torrent_path = None
        self.selected_file_label.setText("")
        self.magnet_input.clear()
        self.data_dir_input.setText(self._settings.default_download_dir)
        self.time_limit_spin.setValue(0)
        self.data_limit_spin.setValue(0)
        self.ratio_limit_spin.setValue(0)

    # --------------------------------------------------------------- signals

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        if not self._share_limit_service.is_tracked(info_hash):
            return
        row = self._rows.get(info_hash)
        if row is None:
            row = self._add_row(info_hash, record)
        self._update_row(row, info_hash, record)

    def _on_torrent_removed(self, info_hash: str) -> None:
        # ShareLimitService untracks itself (connected to the same signal),
        # so this only needs to worry about its own table row.
        row = self._rows.pop(info_hash, None)
        if row is not None:
            self.table.removeRow(row)
            self._reindex_rows()
            self._apply_filter()

    def _on_limit_reached(self, info_hash: str, reason: str) -> None:
        row = self._rows.get(info_hash)
        if row is not None:
            self.table.item(row, 5).setText(_limit_reason_label(reason))

    # ------------------------------------------------------------------ rows

    def _add_row(self, info_hash: str, record: TorrentRecord) -> int:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[info_hash] = row

        self.table.setItem(row, 0, QTableWidgetItem(record.name or info_hash[:12]))
        self.table.item(row, 0).setToolTip(record.name or info_hash[:12])
        for col in range(1, 6):
            self.table.setItem(row, col, QTableWidgetItem(""))

        actions = QWidget(self.table)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(2, 2, 2, 2)
        pause_button = QPushButton(tr("share_tab.pause"), actions)
        pause_button.setObjectName("pauseResumeButton")
        pause_button.clicked.connect(lambda checked=False, ih=info_hash: self._on_pause_resume_clicked(ih))
        actions_layout.addWidget(pause_button)
        remove_button = make_remove_button(
            actions,
            lambda ih=info_hash: self._session_manager.remove_torrent(ih),
            lambda ih=info_hash: self._session_manager.remove_torrent(ih, delete_files=True),
        )
        actions_layout.addWidget(remove_button)
        self.table.setCellWidget(row, 6, actions)

        self._apply_filter()
        return row

    def _reindex_rows(self) -> None:
        reindex_rows_by_info_hash(self.table, self._rows)

    # ----------------------------------------------------------------- filter

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self._filter_text.strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            name = item.text() if item is not None else ""
            self.table.setRowHidden(row, bool(needle) and needle not in name.lower())

    def _update_row(self, row: int, info_hash: str, record: TorrentRecord) -> None:
        self.table.item(row, 0).setText(record.name or info_hash[:12])
        self.table.item(row, 0).setToolTip(record.name or info_hash[:12])
        self.table.item(row, 0).setData(Qt.UserRole, info_hash)
        self.table.item(row, 1).setText(human_rate(record.upload_rate))

        elapsed, uploaded = self._share_limit_service.progress(info_hash, record)
        self.table.item(row, 2).setText(human_size(uploaded))

        limit = self._share_limit_service.limit_for(info_hash)
        if limit is not None and limit.time_limit_seconds is not None:
            self.table.item(row, 3).setText(f"{human_eta(elapsed)} / {human_eta(limit.time_limit_seconds)}")
        else:
            self.table.item(row, 3).setText(human_eta(elapsed))

        if limit is not None and limit.data_limit_bytes is not None:
            self.table.item(row, 4).setText(f"{human_size(uploaded)} / {human_size(limit.data_limit_bytes)}")
        else:
            self.table.item(row, 4).setText(tr("share_tab.unlimited"))

        if limit is not None and limit.reached:
            self.table.item(row, 5).setText(_limit_reason_label(limit.reached_reason))
        else:
            self.table.item(row, 5).setText(_state_label(record.state))

    def _on_pause_resume_clicked(self, info_hash: str) -> None:
        record = self._session_manager.get_record(info_hash)
        if record is None:
            return
        if record.state == TorrentState.PAUSED:
            self._session_manager.resume_torrent(info_hash)
        else:
            self._session_manager.pause_torrent(info_hash)

    # --------------------------------------------------------- context menu

    def _on_context_menu_requested(self, pos) -> None:
        info_hash = info_hash_at(self.table, pos)
        if not info_hash:
            return
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
        remove_action = menu.addAction(tr("common.remove"))
        remove_action.triggered.connect(
            lambda: confirm_and_remove(
                self.table,
                lambda: self._session_manager.remove_torrent(info_hash),
                lambda: self._session_manager.remove_torrent(info_hash, delete_files=True),
            )
        )
        return menu

    def _on_move_storage_requested(self, info_hash: str) -> None:
        new_dir = QFileDialog.getExistingDirectory(self, tr("common.move_storage_dialog_title"))
        if new_dir:
            self._session_manager.move_storage(info_hash, new_dir)
