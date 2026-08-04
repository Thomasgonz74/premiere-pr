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
from torrent2000.i18n.translator import tr
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

        self.source_box = QGroupBox(tr("add_tab.source_group"), self)
        source_layout = QVBoxLayout(self.source_box)

        self.drop_zone = DropZoneWidget(self.source_box)
        self.drop_zone.torrent_file_dropped.connect(self._on_torrent_file_selected)
        source_layout.addWidget(self.drop_zone)

        browse_row = QHBoxLayout()
        self.browse_button = QPushButton(tr("add_tab.browse_torrent"), self.source_box)
        self.browse_button.clicked.connect(self._on_browse_clicked)
        browse_row.addWidget(self.browse_button)
        self.selected_file_label = QLabel("", self.source_box)
        browse_row.addWidget(self.selected_file_label, 1)
        source_layout.addLayout(browse_row)

        magnet_row = QHBoxLayout()
        self.magnet_label = QLabel(tr("add_tab.magnet_label"), self.source_box)
        magnet_row.addWidget(self.magnet_label)
        self.magnet_input = QLineEdit(self.source_box)
        self.magnet_input.setPlaceholderText("magnet:?xt=urn:btih:...")
        magnet_row.addWidget(self.magnet_input, 1)
        source_layout.addLayout(magnet_row)

        layout.addWidget(self.source_box)

        self.dest_box = QGroupBox(tr("add_tab.destination_group"), self)
        dest_layout = QHBoxLayout(self.dest_box)
        self.dest_input = QLineEdit(settings.default_download_dir, self.dest_box)
        dest_layout.addWidget(self.dest_input, 1)
        self.dest_browse_button = QPushButton(tr("common.browse"), self.dest_box)
        self.dest_browse_button.clicked.connect(self._on_browse_dest_clicked)
        dest_layout.addWidget(self.dest_browse_button)
        layout.addWidget(self.dest_box)

        self.analysis_box = QGroupBox(tr("add_tab.analysis_group"), self)
        analysis_layout = QVBoxLayout(self.analysis_box)

        analysis_controls = QHBoxLayout()
        self.analyze_button = QPushButton(tr("add_tab.analyze_button"), self.analysis_box)
        self.analyze_button.clicked.connect(self._on_analyze_clicked)
        analysis_controls.addWidget(self.analyze_button)
        self.threshold_label = QLabel(tr("add_tab.threshold_label"), self.analysis_box)
        analysis_controls.addWidget(self.threshold_label)
        self.threshold_spin = QSpinBox(self.analysis_box)
        self.threshold_spin.setRange(0, 100)
        self.threshold_spin.setValue(settings.danger_auto_exclude_threshold)
        analysis_controls.addWidget(self.threshold_spin)
        analysis_controls.addStretch(1)
        analysis_layout.addLayout(analysis_controls)

        self.status_label = QLabel("", self.analysis_box)
        analysis_layout.addWidget(self.status_label)

        self.file_tree = FileTreeRiskWidget(self.analysis_box)
        analysis_layout.addWidget(self.file_tree)

        selection_row = QHBoxLayout()
        self.check_all_button = QPushButton(tr("add_tab.check_all"), self.analysis_box)
        self.check_all_button.clicked.connect(self.file_tree.check_all)
        selection_row.addWidget(self.check_all_button)
        self.uncheck_all_button = QPushButton(tr("add_tab.uncheck_all"), self.analysis_box)
        self.uncheck_all_button.clicked.connect(self.file_tree.uncheck_all)
        selection_row.addWidget(self.uncheck_all_button)
        selection_row.addStretch(1)
        analysis_layout.addLayout(selection_row)

        layout.addWidget(self.analysis_box, 1)

        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.start_button = QPushButton(tr("add_tab.start_button"), self)
        self.start_button.clicked.connect(self._on_start_clicked)
        start_row.addWidget(self.start_button)
        layout.addLayout(start_row)

        self._session_manager.metadata_received.connect(self._on_metadata_received)

    # ----------------------------------------------------------- retranslate

    def retranslate_ui(self) -> None:
        self.source_box.setTitle(tr("add_tab.source_group"))
        self.drop_zone.retranslate_ui()
        self.browse_button.setText(tr("add_tab.browse_torrent"))
        self.magnet_label.setText(tr("add_tab.magnet_label"))
        self.dest_box.setTitle(tr("add_tab.destination_group"))
        self.dest_browse_button.setText(tr("common.browse"))
        self.analysis_box.setTitle(tr("add_tab.analysis_group"))
        self.analyze_button.setText(tr("add_tab.analyze_button"))
        self.threshold_label.setText(tr("add_tab.threshold_label"))
        self.file_tree.retranslate_ui()
        self.check_all_button.setText(tr("add_tab.check_all"))
        self.uncheck_all_button.setText(tr("add_tab.uncheck_all"))
        self.start_button.setText(tr("add_tab.start_button"))

    # ---------------------------------------------------------------- source

    def _on_browse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("add_tab.choose_torrent_title"), "", "Torrent (*.torrent)")
        if path:
            self._on_torrent_file_selected(path)

    def open_torrent_file(self, path: str) -> None:
        """Entry point for the .torrent file association: pre-fills the form
        exactly like a manual browse/drop would, so the user still goes
        through Analyser/Démarrer themselves rather than the danger-scanning
        step being silently skipped just because the file arrived via
        double-click instead of drag-and-drop."""
        self._on_torrent_file_selected(path)

    def open_magnet(self, uri: str) -> None:
        """Entry point for the magnet: URI protocol association."""
        self._torrent_path = None
        self._pending_magnet_hash = None
        self.selected_file_label.setText("")
        self.file_tree.clear()
        self.status_label.setText("")
        self.magnet_input.setText(uri)

    def _on_torrent_file_selected(self, path: str) -> None:
        self._torrent_path = path
        self._pending_magnet_hash = None
        self.selected_file_label.setText(path)
        self.magnet_input.clear()
        self.file_tree.clear()
        self.status_label.setText("")

    def _on_browse_dest_clicked(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("add_tab.choose_dest_title"), self.dest_input.text())
        if directory:
            self.dest_input.setText(directory)

    # -------------------------------------------------------------- analysis

    def _on_analyze_clicked(self) -> None:
        if self._torrent_path:
            try:
                files = files_from_torrent_path(self._torrent_path)
            except Exception as exc:
                QMessageBox.warning(self, tr("add_tab.analysis_failed_title"), tr("add_tab.analysis_failed_message", error=exc))
                return
            result = scan_files(files)
            self.file_tree.load_scan_result(result, self.threshold_spin.value())
            self.status_label.setText(tr("add_tab.files_analyzed", count=len(files)))
            return

        magnet_uri = self.magnet_input.text().strip()
        if magnet_uri:
            if self._pending_magnet_hash is None:
                info_hash = self._session_manager.add_torrent_from_magnet(magnet_uri, self.dest_input.text())
                self._pending_magnet_hash = info_hash
            self.status_label.setText(tr("add_tab.awaiting_metadata"))
            return

        QMessageBox.information(self, tr("add_tab.no_source_title"), tr("add_tab.no_source_message"))

    def _on_metadata_received(self, info_hash: str) -> None:
        if info_hash != self._pending_magnet_hash:
            return
        files = self._session_manager.get_torrent_files(info_hash)
        result = scan_files(files)
        self.file_tree.load_scan_result(result, self.threshold_spin.value())
        self.status_label.setText(tr("add_tab.metadata_received", count=len(files)))

    # ------------------------------------------------------------------ start

    def _on_start_clicked(self) -> None:
        dest = self.dest_input.text().strip()
        if not dest:
            QMessageBox.warning(self, tr("add_tab.missing_dest_title"), tr("add_tab.missing_dest_message"))
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

        QMessageBox.information(self, tr("add_tab.no_source_title"), tr("add_tab.no_source_message"))

    def _reset_form(self) -> None:
        self._torrent_path = None
        self._pending_magnet_hash = None
        self.selected_file_label.setText("")
        self.magnet_input.clear()
        self.file_tree.clear()
        self.status_label.setText(tr("add_tab.torrent_added"))
