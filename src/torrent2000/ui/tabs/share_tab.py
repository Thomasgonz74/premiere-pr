from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
from torrent2000.ui.widgets.drop_zone import DropZoneWidget
from torrent2000.utils.formatting import human_eta, human_rate, human_size

COLUMNS = ["Nom", "↑ Vitesse", "Envoyé (session)", "Temps", "Données", "État", "Action"]

_STATE_LABELS = {
    TorrentState.SEEDING: "Partage en cours",
    TorrentState.PAUSED: "En pause",
    TorrentState.QUEUED: "En attente",
    TorrentState.CHECKING_METADATA: "Vérification...",
    TorrentState.ERROR: "Erreur",
}

_LIMIT_REASON_LABELS = {"time": "Limite de temps atteinte", "data": "Limite de données atteinte"}


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

        layout = QVBoxLayout(self)

        source_box = QGroupBox("Ajouter un partage", self)
        source_layout = QVBoxLayout(source_box)

        self.drop_zone = DropZoneWidget(source_box)
        self.drop_zone.torrent_file_dropped.connect(self._on_torrent_file_selected)
        source_layout.addWidget(self.drop_zone)

        browse_row = QHBoxLayout()
        self.browse_button = QPushButton("Parcourir un fichier .torrent...", source_box)
        self.browse_button.clicked.connect(self._on_browse_clicked)
        browse_row.addWidget(self.browse_button)
        self.selected_file_label = QLabel("", source_box)
        browse_row.addWidget(self.selected_file_label, 1)
        source_layout.addLayout(browse_row)

        magnet_row = QHBoxLayout()
        magnet_row.addWidget(QLabel("Lien magnet:", source_box))
        self.magnet_input = QLineEdit(source_box)
        self.magnet_input.setPlaceholderText("magnet:?xt=urn:btih:...")
        magnet_row.addWidget(self.magnet_input, 1)
        source_layout.addLayout(magnet_row)

        data_row = QHBoxLayout()
        data_row.addWidget(QLabel("Dossier contenant déjà les fichiers :", source_box))
        self.data_dir_input = QLineEdit(source_box)
        data_row.addWidget(self.data_dir_input, 1)
        data_browse_button = QPushButton("Parcourir...", source_box)
        data_browse_button.clicked.connect(self._on_browse_data_dir)
        data_row.addWidget(data_browse_button)
        source_layout.addLayout(data_row)

        limits_row = QHBoxLayout()
        limits_row.addWidget(QLabel("Limite de temps :", source_box))
        self.time_limit_spin = QSpinBox(source_box)
        self.time_limit_spin.setRange(0, 999)
        self.time_limit_spin.setSuffix(" h (0 = illimité)")
        limits_row.addWidget(self.time_limit_spin)
        limits_row.addSpacing(16)
        limits_row.addWidget(QLabel("Limite de données :", source_box))
        self.data_limit_spin = QSpinBox(source_box)
        self.data_limit_spin.setRange(0, 1_000_000)
        self.data_limit_spin.setSuffix(" Mo (0 = illimité)")
        limits_row.addWidget(self.data_limit_spin)
        limits_row.addStretch(1)
        source_layout.addLayout(limits_row)

        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.start_button = QPushButton("Démarrer le partage", source_box)
        self.start_button.clicked.connect(self._on_start_clicked)
        start_row.addWidget(self.start_button)
        source_layout.addLayout(start_row)

        layout.addWidget(source_box)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        self._session_manager.torrent_status_updated.connect(self._on_status_updated)
        self._session_manager.torrent_removed.connect(self._on_torrent_removed)
        self._share_limit_service.limit_reached.connect(self._on_limit_reached)

    # ---------------------------------------------------------------- source

    def _on_browse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier .torrent", "", "Torrent (*.torrent)")
        if path:
            self._on_torrent_file_selected(path)

    def _on_torrent_file_selected(self, path: str) -> None:
        self._torrent_path = path
        self.selected_file_label.setText(path)
        self.magnet_input.clear()

    def _on_browse_data_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Dossier contenant déjà les fichiers", self.data_dir_input.text())
        if directory:
            self.data_dir_input.setText(directory)

    # ------------------------------------------------------------------ start

    def _on_start_clicked(self) -> None:
        data_dir = self.data_dir_input.text().strip()
        if not data_dir:
            QMessageBox.warning(
                self, "Dossier manquant", "Indiquez le dossier qui contient déjà les fichiers à partager."
            )
            return

        time_limit = self.time_limit_spin.value() * 3600 or None
        data_limit = self.data_limit_spin.value() * 1024 * 1024 or None

        if self._torrent_path:
            info_hash = self._session_manager.add_torrent_from_file(self._torrent_path, data_dir)
        else:
            magnet_uri = self.magnet_input.text().strip()
            if not magnet_uri:
                QMessageBox.information(
                    self, "Aucune source", "Sélectionnez un fichier .torrent ou saisissez un lien magnet."
                )
                return
            info_hash = self._session_manager.add_torrent_from_magnet(magnet_uri, data_dir)
            self._session_manager.start_after_analysis(info_hash)

        self._share_limit_service.track(info_hash, time_limit, data_limit)
        self._reset_form()

    def _reset_form(self) -> None:
        self._torrent_path = None
        self.selected_file_label.setText("")
        self.magnet_input.clear()
        self.data_dir_input.clear()
        self.time_limit_spin.setValue(0)
        self.data_limit_spin.setValue(0)

    # --------------------------------------------------------------- signals

    def _on_status_updated(self, info_hash: str, record: TorrentRecord) -> None:
        if not self._share_limit_service.is_tracked(info_hash):
            return
        row = self._rows.get(info_hash)
        if row is None:
            row = self._add_row(info_hash, record)
        self._update_row(row, info_hash, record)

    def _on_torrent_removed(self, info_hash: str) -> None:
        self._share_limit_service.untrack(info_hash)
        row = self._rows.pop(info_hash, None)
        if row is not None:
            self.table.removeRow(row)
            self._reindex_rows()

    def _on_limit_reached(self, info_hash: str, reason: str) -> None:
        row = self._rows.get(info_hash)
        if row is not None:
            self.table.item(row, 5).setText(_LIMIT_REASON_LABELS.get(reason, "Limite atteinte"))

    # ------------------------------------------------------------------ rows

    def _add_row(self, info_hash: str, record: TorrentRecord) -> int:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[info_hash] = row

        self.table.setItem(row, 0, QTableWidgetItem(record.name or info_hash[:12]))
        for col in range(1, 6):
            self.table.setItem(row, col, QTableWidgetItem(""))

        actions = QWidget(self.table)
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(2, 2, 2, 2)
        pause_button = QPushButton("Pause", actions)
        pause_button.setObjectName("pauseResumeButton")
        pause_button.clicked.connect(lambda checked=False, ih=info_hash: self._on_pause_resume_clicked(ih))
        actions_layout.addWidget(pause_button)
        remove_button = QPushButton("Retirer", actions)
        remove_button.setObjectName("dangerButton")
        remove_button.clicked.connect(lambda checked=False, ih=info_hash: self._session_manager.remove_torrent(ih))
        actions_layout.addWidget(remove_button)
        self.table.setCellWidget(row, 6, actions)

        return row

    def _reindex_rows(self) -> None:
        self._rows.clear()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                info_hash = item.data(Qt.UserRole)
                if info_hash:
                    self._rows[info_hash] = row

    def _update_row(self, row: int, info_hash: str, record: TorrentRecord) -> None:
        self.table.item(row, 0).setText(record.name or info_hash[:12])
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
            self.table.item(row, 4).setText("Illimité")

        if limit is not None and limit.reached:
            self.table.item(row, 5).setText(_LIMIT_REASON_LABELS.get(limit.reached_reason, "Limite atteinte"))
        else:
            self.table.item(row, 5).setText(_STATE_LABELS.get(record.state, str(record.state)))

    def _on_pause_resume_clicked(self, info_hash: str) -> None:
        record = self._session_manager.get_record(info_hash)
        if record is None:
            return
        if record.state == TorrentState.PAUSED:
            self._session_manager.resume_torrent(info_hash)
        else:
            self._session_manager.pause_torrent(info_hash)
