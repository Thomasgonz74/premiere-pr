from urllib.parse import parse_qs, urlsplit

import libtorrent as lt
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from torrent2000.config.settings import Settings
from torrent2000.danger_scanner import FileEntry, scan_files
from torrent2000.engine.disk_space_monitor import free_space_mb
from torrent2000.engine.routing_rules import RoutingRuleStore, resolve_destination
from torrent2000.engine.session_manager import SessionManager
from torrent2000.engine.torrent_files import files_from_torrent_path
from torrent2000.i18n.translator import tr
from torrent2000.ui.dialogs.create_torrent_dialog import CreateTorrentDialog
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
        # Instantiated once here (not per-selection) to avoid re-reading
        # routing_rules.json on every file/magnet selection -- see
        # engine/routing_rules.py.
        self._routing_store = RoutingRuleStore()
        self._torrent_path: str | None = None
        self._pending_magnet_hash: str | None = None
        # Only True once metadata for _pending_magnet_hash has actually been
        # scanned -- guards _on_start_clicked against starting a magnet whose
        # analysis was requested but hasn't come back yet.
        self._magnet_metadata_ready = False

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Without a scroll area, this tab's combined content (source group
        # with its fixed-height drop zone, destination group, analysis
        # group with the file tree) bubbles its minimum height up through
        # the tab widget to the frameless top-level window -- once the
        # window is resized below that, Qt compresses the group boxes past
        # their own minimum instead of scrolling, which visually overlaps
        # their contents. Same fix as ProfileTab already uses; see its own
        # comment on this exact problem.
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)

        self.source_box = QGroupBox(tr("add_tab.source_group"), scroll_content)
        source_layout = QVBoxLayout(self.source_box)

        # Deliberately separate from start_button below: this creates a new
        # .torrent from a local file/folder rather than adding an existing
        # one, so it lives in its own small row rather than looking like a
        # second way to do what "Démarrer" already does.
        create_torrent_row = QHBoxLayout()
        create_torrent_row.addStretch(1)
        self.create_torrent_button = QPushButton(tr("add_tab.create_torrent_button"), self.source_box)
        self.create_torrent_button.clicked.connect(self._on_create_torrent_clicked)
        create_torrent_row.addWidget(self.create_torrent_button)
        source_layout.addLayout(create_torrent_row)

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
        self.magnet_input.textChanged.connect(self._maybe_apply_routing_rule_for_magnet)
        magnet_row.addWidget(self.magnet_input, 1)
        source_layout.addLayout(magnet_row)

        layout.addWidget(self.source_box)

        self.dest_box = QGroupBox(tr("add_tab.destination_group"), scroll_content)
        dest_layout = QHBoxLayout(self.dest_box)
        self.dest_input = QLineEdit(settings.default_download_dir, self.dest_box)
        dest_layout.addWidget(self.dest_input, 1)
        self.dest_browse_button = QPushButton(tr("common.browse"), self.dest_box)
        self.dest_browse_button.clicked.connect(self._on_browse_dest_clicked)
        dest_layout.addWidget(self.dest_browse_button)
        layout.addWidget(self.dest_box)

        self.analysis_box = QGroupBox(tr("add_tab.analysis_group"), scroll_content)
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

        scroll_area.setWidget(scroll_content)
        outer_layout.addWidget(scroll_area, 1)

        # Kept outside the scroll area, pinned at the bottom, so it's always
        # reachable without having to scroll all the way down first -- same
        # pattern as ProfileTab's Save button.
        start_row = QHBoxLayout()
        start_row.setContentsMargins(8, 6, 8, 8)
        start_row.addStretch(1)
        self.start_button = QPushButton(tr("add_tab.start_button"), self)
        self.start_button.clicked.connect(self._on_start_clicked)
        start_row.addWidget(self.start_button)
        outer_layout.addLayout(start_row)

        self._session_manager.metadata_received.connect(self._on_metadata_received)

    # ----------------------------------------------------------- retranslate

    def retranslate_ui(self) -> None:
        self.source_box.setTitle(tr("add_tab.source_group"))
        self.create_torrent_button.setText(tr("add_tab.create_torrent_button"))
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

    def _on_create_torrent_clicked(self) -> None:
        CreateTorrentDialog(self).exec()

    def _on_browse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("add_tab.choose_torrent_title"), "", "Torrent (*.torrent)")
        if path:
            self._on_torrent_file_selected(path)

    def open_torrent_file(self, path: str) -> None:
        """Entry point for the .torrent file association: pre-fills the form
        exactly like a manual browse/drop would (including the automatic
        danger scan), so the file association can't be used to bypass
        analysis just because the file arrived via double-click instead of
        drag-and-drop."""
        self._on_torrent_file_selected(path)

    def open_magnet(self, uri: str) -> None:
        """Entry point for the magnet: URI protocol association."""
        self._torrent_path = None
        self._pending_magnet_hash = None
        self._magnet_metadata_ready = False
        self.selected_file_label.setText("")
        self.file_tree.clear()
        self.status_label.setText("")
        self.magnet_input.setText(uri)

    def _on_torrent_file_selected(self, path: str) -> None:
        self._torrent_path = path
        self._pending_magnet_hash = None
        self._magnet_metadata_ready = False
        self.selected_file_label.setText(path)
        self.magnet_input.clear()
        self.file_tree.clear()
        self.status_label.setText("")
        # Best-effort routing-rule pre-fill, ahead of the danger-scan
        # analysis below -- neither depends on the other's result.
        self._maybe_apply_routing_rule_for_file(path)
        # Analyze immediately -- the user must be able to click "Démarrer"
        # right after selecting a file and still have the auto-exclusion
        # threshold applied, without an explicit "Analyser" click first.
        self._analyze_file_source()

    def _on_browse_dest_clicked(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("add_tab.choose_dest_title"), self.dest_input.text())
        if directory:
            self.dest_input.setText(directory)

    # ------------------------------------------------------------- routing

    def _maybe_apply_routing_rule_for_file(self, path: str) -> None:
        """Pre-fills dest_input from the first routing rule (see
        engine/routing_rules.py) whose pattern matches this .torrent's real
        name or one of its trackers -- read straight off the file via
        libtorrent, ahead of session_manager.add_torrent_from_file ever
        being called. Leaves the field untouched if the file can't be
        parsed (e.g. a not-yet-fully-written drop) or no rule matches."""
        try:
            ti = lt.torrent_info(path)
            name = ti.name()
            trackers = [entry.url for entry in ti.trackers()]
        except Exception:
            return
        self._apply_resolved_destination(name=name, trackers=trackers)

    def _maybe_apply_routing_rule_for_magnet(self, uri: str) -> None:
        """Same idea as _maybe_apply_routing_rule_for_file, but for a magnet
        URI: only its dn= display-name query parameter is available before
        metadata has actually been fetched, so only match_field == "name"
        rules can ever apply at this stage -- there is no tracker list yet."""
        name = parse_qs(urlsplit(uri).query).get("dn", [""])[0]
        if not name:
            return
        self._apply_resolved_destination(name=name, trackers=None)

    def _apply_resolved_destination(self, name: str, trackers: list[str] | None) -> None:
        current = self.dest_input.text()
        resolved = resolve_destination(self._routing_store.list_rules(), current, name=name, trackers=trackers)
        if resolved != current:
            self.dest_input.setText(resolved)

    # -------------------------------------------------------------- analysis

    def _on_analyze_clicked(self) -> None:
        if self._analyze_file_source():
            return
        if self._analyze_magnet_source():
            return

        QMessageBox.information(self, tr("add_tab.no_source_title"), tr("add_tab.no_source_message"))

    def _analyze_file_source(self) -> bool:
        """Scan self._torrent_path and populate the file tree, applying the
        auto-exclusion threshold. Returns False only when there is no
        selected .torrent file to analyze (so the magnet path can be tried
        instead); a failed scan still returns True since a file source was
        present and handled (via the warning dialog)."""
        if not self._torrent_path:
            return False
        files = self._read_torrent_files_or_warn(self._torrent_path)
        if files is None:
            return True
        result = scan_files(files)
        self.file_tree.load_scan_result(result, self.threshold_spin.value())
        self.status_label.setText(tr("add_tab.files_analyzed", count=len(files)))
        return True

    def _read_torrent_files_or_warn(self, path: str) -> list[FileEntry] | None:
        """Read path's file list off disk, showing the same graceful
        'analysis failed' dialog _analyze_file_source always has and
        returning None on any parse error (e.g. a corrupted/invalid
        .torrent) -- used by every call site that re-reads
        self._torrent_path after the initial analysis, so a file that
        turned out to be unreadable can never reach an unguarded
        files_from_torrent_path() call later (see _on_start_clicked)."""
        try:
            return files_from_torrent_path(path)
        except Exception as exc:
            QMessageBox.warning(self, tr("add_tab.analysis_failed_title"), tr("add_tab.analysis_failed_message", error=exc))
            return None

    def _analyze_magnet_source(self) -> bool:
        """Add (if not already pending) the magnet currently in the input
        field and await its metadata. Returns False only when the field is
        empty."""
        magnet_uri = self.magnet_input.text().strip()
        if not magnet_uri:
            return False
        if self._pending_magnet_hash is None:
            self._magnet_metadata_ready = False
            info_hash = self._session_manager.add_torrent_from_magnet(magnet_uri, self.dest_input.text())
            self._pending_magnet_hash = info_hash
        self.status_label.setText(tr("add_tab.awaiting_metadata"))
        return True

    def _on_metadata_received(self, info_hash: str) -> None:
        if info_hash != self._pending_magnet_hash:
            return
        files = self._session_manager.get_torrent_files(info_hash)
        result = scan_files(files)
        self.file_tree.load_scan_result(result, self.threshold_spin.value())
        self._magnet_metadata_ready = True
        self.status_label.setText(tr("add_tab.metadata_received", count=len(files)))

    # ------------------------------------------------------------------ start

    def _on_start_clicked(self) -> None:
        dest = self.dest_input.text().strip()
        if not dest:
            QMessageBox.warning(self, tr("add_tab.missing_dest_title"), tr("add_tab.missing_dest_message"))
            return

        excluded = self.file_tree.excluded_indices() if self.file_tree.topLevelItemCount() else set()

        if self._pending_magnet_hash is not None:
            if not self._magnet_metadata_ready:
                # Metadata (and therefore the danger scan) hasn't come back
                # yet -- starting now would apply zero exclusions.
                QMessageBox.information(
                    self,
                    tr("add_tab.magnet_analysis_required_title"),
                    tr("add_tab.magnet_analysis_required_message"),
                )
                return
            if excluded:
                self._session_manager.exclude_files(self._pending_magnet_hash, excluded)
            self._session_manager.start_after_analysis(self._pending_magnet_hash)
            self._reset_form()
            self.torrent_started.emit()
            return

        if self._torrent_path:
            files = self._read_torrent_files_or_warn(self._torrent_path)
            if files is None:
                return
            total_size = sum(entry.size for entry in files if entry.index not in excluded)
            free_mb = free_space_mb(dest)
            if free_mb is not None and free_mb < total_size / (1024 * 1024):
                QMessageBox.warning(
                    self, tr("add_tab.insufficient_space_title"), tr("add_tab.insufficient_space_message")
                )
                return
            try:
                self._session_manager.add_torrent_from_file(self._torrent_path, dest, excluded)
            except Exception:
                QMessageBox.information(self, tr("add_tab.duplicate_title"), tr("add_tab.duplicate_message"))
                return
            self._reset_form()
            self.torrent_started.emit()
            return

        magnet_uri = self.magnet_input.text().strip()
        if magnet_uri:
            # No prior "Analyser" click for this magnet -- add it and wait
            # for metadata instead of starting immediately with zero
            # exclusions. The user re-clicks "Démarrer" once analysis lands.
            try:
                self._analyze_magnet_source()
            except Exception:
                QMessageBox.information(self, tr("add_tab.duplicate_title"), tr("add_tab.duplicate_message"))
                return
            QMessageBox.information(
                self,
                tr("add_tab.magnet_analysis_required_title"),
                tr("add_tab.magnet_analysis_required_message"),
            )
            return

        QMessageBox.information(self, tr("add_tab.no_source_title"), tr("add_tab.no_source_message"))

    def _reset_form(self) -> None:
        self._torrent_path = None
        self._pending_magnet_hash = None
        self._magnet_metadata_ready = False
        self.selected_file_label.setText("")
        self.magnet_input.clear()
        self.file_tree.clear()
        self.status_label.setText(tr("add_tab.torrent_added"))
