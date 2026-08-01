from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from torrent2000.config.settings import Settings
from torrent2000.danger_scanner import scan_files
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_files import files_from_torrent_path
from torrent2000.ui.widgets.drop_zone import DropZoneWidget
from torrent2000.ui.widgets.file_tree_risk import FileTreeRiskWidget


class AddTorrentTab(QWidget):
    # Emitted right after a torrent is actually started (not just added-and-
    # awaiting-analysis) so MainWindow can switch to the Downloads tab.
    torrent_started = Signal()

    def __init__(self, session_manager: SessionManager, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._settings = settings
        self._torrent_path: str | None = None
        self._pending_magnet_hash: str | None = None

        layout = QVBoxLayout(self)

        source_box = QGroupBox("Source du torrent", self)
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

        layout.addWidget(source_box)

        dest_box = QGroupBox("Destination", self)
        dest_layout = QHBoxLayout(dest_box)
        self.dest_input = QLineEdit(settings.default_download_dir, dest_box)
        dest_layout.addWidget(self.dest_input, 1)
        self.dest_browse_button = QPushButton("Parcourir...", dest_box)
        self.dest_browse_button.clicked.connect(self._on_browse_dest_clicked)
        dest_layout.addWidget(self.dest_browse_button)
        layout.addWidget(dest_box)

        analysis_box = QGroupBox("Analyse des fichiers (facultative)", self)
        analysis_layout = QVBoxLayout(analysis_box)

        analysis_controls = QHBoxLayout()
        self.analyze_button = QPushButton("Analyser", analysis_box)
        self.analyze_button.clicked.connect(self._on_analyze_clicked)
        analysis_controls.addWidget(self.analyze_button)
        analysis_controls.addWidget(QLabel("Seuil d'auto-exclusion (score ≥):", analysis_box))
        self.threshold_spin = QSpinBox(analysis_box)
        self.threshold_spin.setRange(0, 100)
        self.threshold_spin.setValue(settings.danger_auto_exclude_threshold)
        analysis_controls.addWidget(self.threshold_spin)
        analysis_controls.addStretch(1)
        analysis_layout.addLayout(analysis_controls)

        self.status_label = QLabel("", analysis_box)
        analysis_layout.addWidget(self.status_label)

        self.file_tree = FileTreeRiskWidget(analysis_box)
        analysis_layout.addWidget(self.file_tree)

        selection_row = QHBoxLayout()
        self.check_all_button = QPushButton("Tout cocher", analysis_box)
        self.check_all_button.clicked.connect(self.file_tree.check_all)
        selection_row.addWidget(self.check_all_button)
        self.uncheck_all_button = QPushButton("Tout décocher", analysis_box)
        self.uncheck_all_button.clicked.connect(self.file_tree.uncheck_all)
        selection_row.addWidget(self.uncheck_all_button)
        selection_row.addStretch(1)
        analysis_layout.addLayout(selection_row)

        layout.addWidget(analysis_box, 1)

        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.start_button = QPushButton("Démarrer le téléchargement", self)
        self.start_button.clicked.connect(self._on_start_clicked)
        start_row.addWidget(self.start_button)
        layout.addLayout(start_row)

        self._session_manager.metadata_received.connect(self._on_metadata_received)

    # ---------------------------------------------------------------- source

    def _on_browse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier .torrent", "", "Torrent (*.torrent)")
        if path:
            self._on_torrent_file_selected(path)

    def _on_torrent_file_selected(self, path: str) -> None:
        self._torrent_path = path
        self._pending_magnet_hash = None
        self.selected_file_label.setText(path)
        self.magnet_input.clear()
        self.file_tree.clear()
        self.status_label.setText("")

    def _on_browse_dest_clicked(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choisir le dossier de destination", self.dest_input.text())
        if directory:
            self.dest_input.setText(directory)

    # -------------------------------------------------------------- analysis

    def _on_analyze_clicked(self) -> None:
        if self._torrent_path:
            try:
                files = files_from_torrent_path(self._torrent_path)
            except Exception as exc:
                QMessageBox.warning(self, "Analyse impossible", f"Impossible de lire ce fichier .torrent :\n{exc}")
                return
            result = scan_files(files)
            self.file_tree.load_scan_result(result, self.threshold_spin.value())
            self.status_label.setText(f"{len(files)} fichier(s) analysé(s).")
            return

        magnet_uri = self.magnet_input.text().strip()
        if magnet_uri:
            if self._pending_magnet_hash is None:
                info_hash = self._session_manager.add_torrent_from_magnet(magnet_uri, self.dest_input.text())
                self._pending_magnet_hash = info_hash
            self.status_label.setText(
                "En attente des métadonnées du magnet (recherche de pairs)... "
                "l'analyse s'affichera automatiquement dès qu'elles arrivent."
            )
            return

        QMessageBox.information(self, "Aucune source", "Sélectionnez un fichier .torrent ou saisissez un lien magnet.")

    def _on_metadata_received(self, info_hash: str) -> None:
        if info_hash != self._pending_magnet_hash:
            return
        files = self._session_manager.get_torrent_files(info_hash)
        result = scan_files(files)
        self.file_tree.load_scan_result(result, self.threshold_spin.value())
        self.status_label.setText(f"Métadonnées reçues -- {len(files)} fichier(s) analysé(s).")

    # ------------------------------------------------------------------ start

    def _on_start_clicked(self) -> None:
        dest = self.dest_input.text().strip()
        if not dest:
            QMessageBox.warning(self, "Destination manquante", "Choisissez un dossier de destination.")
            return

        excluded = self.file_tree.excluded_indices() if self.file_tree.topLevelItemCount() else set()

        if self._pending_magnet_hash is not None:
            if excluded:
                self._session_manager.exclude_files(self._pending_magnet_hash, excluded)
            self._session_manager.start_after_analysis(self._pending_magnet_hash)
            self._reset_form()
            self.torrent_started.emit()
            return

        if self._torrent_path:
            self._session_manager.add_torrent_from_file(self._torrent_path, dest, excluded)
            self._reset_form()
            self.torrent_started.emit()
            return

        magnet_uri = self.magnet_input.text().strip()
        if magnet_uri:
            info_hash = self._session_manager.add_torrent_from_magnet(magnet_uri, dest)
            self._session_manager.start_after_analysis(info_hash)
            self._reset_form()
            self.torrent_started.emit()
            return

        QMessageBox.information(self, "Aucune source", "Sélectionnez un fichier .torrent ou saisissez un lien magnet.")

    def _reset_form(self) -> None:
        self._torrent_path = None
        self._pending_magnet_hash = None
        self.selected_file_label.setText("")
        self.magnet_input.clear()
        self.file_tree.clear()
        self.status_label.setText("Téléchargement ajouté.")
