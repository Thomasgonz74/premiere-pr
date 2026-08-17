"""Torrent-creation dialog -- the write side of BitTorrent Torrent 2000
never had (it could previously only consume .torrent files, never produce
one). See engine/torrent_creator.py for the actual libtorrent call.

Not reusing ui/widgets/tracker_editor.py here: that widget is bound to a
SessionManager + a live info_hash (bind()/refresh() both go straight through
session_manager.get_trackers/add_tracker/remove_tracker), so it has nothing
to operate on before a torrent exists. This dialog needs a plain, freestanding
tracker list instead, kept only in memory until "Créer..." is clicked.

A transient, opened-fresh-each-time dialog like FilePriorityDialog/
SpeedGraphDialog/PeerListDialog -- no retranslate_ui(), since it's never kept
alive across a language switch.
"""

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from torrent2000.engine.torrent_creator import create_torrent_file
from torrent2000.i18n.translator import tr

logger = logging.getLogger(__name__)

_TORRENT_FILE_FILTER = "Torrent (*.torrent)"


class CreateTorrentDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._source_path: str = ""

        self.setWindowTitle(tr("create_torrent.window_title"))
        self.resize(480, 420)

        layout = QVBoxLayout(self)

        self.source_box = QGroupBox(tr("create_torrent.source_group"), self)
        source_layout = QVBoxLayout(self.source_box)
        self.source_label = QLabel("", self.source_box)
        self.source_label.setWordWrap(True)
        source_layout.addWidget(self.source_label)
        source_buttons_row = QHBoxLayout()
        self.browse_file_button = QPushButton(tr("create_torrent.browse_file_button"), self.source_box)
        self.browse_file_button.clicked.connect(self._on_browse_file_clicked)
        source_buttons_row.addWidget(self.browse_file_button)
        self.browse_folder_button = QPushButton(tr("create_torrent.browse_folder_button"), self.source_box)
        self.browse_folder_button.clicked.connect(self._on_browse_folder_clicked)
        source_buttons_row.addWidget(self.browse_folder_button)
        source_buttons_row.addStretch(1)
        source_layout.addLayout(source_buttons_row)
        layout.addWidget(self.source_box)

        self.trackers_box = QGroupBox(tr("create_torrent.trackers_group"), self)
        trackers_layout = QVBoxLayout(self.trackers_box)
        self.trackers_list = QListWidget(self.trackers_box)
        trackers_layout.addWidget(self.trackers_list)
        tracker_add_row = QHBoxLayout()
        self.tracker_input = QLineEdit(self.trackers_box)
        self.tracker_input.setPlaceholderText("http://tracker.example.com/announce")
        tracker_add_row.addWidget(self.tracker_input, 1)
        self.add_tracker_button = QPushButton(tr("common.add"), self.trackers_box)
        self.add_tracker_button.clicked.connect(self._on_add_tracker_clicked)
        tracker_add_row.addWidget(self.add_tracker_button)
        self.remove_tracker_button = QPushButton(tr("common.remove"), self.trackers_box)
        self.remove_tracker_button.clicked.connect(self._on_remove_tracker_clicked)
        tracker_add_row.addWidget(self.remove_tracker_button)
        trackers_layout.addLayout(tracker_add_row)
        layout.addWidget(self.trackers_box, 1)

        self.private_checkbox = QCheckBox(tr("create_torrent.private_checkbox"), self)
        layout.addWidget(self.private_checkbox)

        comment_row = QHBoxLayout()
        self.comment_label = QLabel(tr("create_torrent.comment_label"), self)
        comment_row.addWidget(self.comment_label)
        self.comment_input = QLineEdit(self)
        comment_row.addWidget(self.comment_input, 1)
        layout.addLayout(comment_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.create_button = QPushButton(tr("create_torrent.create_button"), self)
        self.create_button.clicked.connect(self._on_create_clicked)
        button_row.addWidget(self.create_button)
        self.close_button = QPushButton(tr("common.cancel"), self)
        self.close_button.clicked.connect(self.reject)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

    # ----------------------------------------------------------------- source

    def _on_browse_file_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("create_torrent.choose_source_file_title"), "")
        if path:
            self._set_source(path)

    def _on_browse_folder_clicked(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("create_torrent.choose_source_folder_title"), "")
        if directory:
            self._set_source(directory)

    def _set_source(self, path: str) -> None:
        self._source_path = path
        self.source_label.setText(path)

    # --------------------------------------------------------------- trackers

    def _on_add_tracker_clicked(self) -> None:
        url = self.tracker_input.text().strip()
        if not url:
            return
        self.trackers_list.addItem(url)
        self.tracker_input.clear()

    def _on_remove_tracker_clicked(self) -> None:
        row = self.trackers_list.currentRow()
        if row >= 0:
            self.trackers_list.takeItem(row)

    # ------------------------------------------------------------------ create

    def _on_create_clicked(self) -> None:
        if not self._source_path:
            QMessageBox.information(self, tr("create_torrent.no_source_title"), tr("create_torrent.no_source_message"))
            return

        default_name = Path(self._source_path).name + ".torrent"
        output_path, _ = QFileDialog.getSaveFileName(
            self, tr("create_torrent.choose_output_title"), default_name, _TORRENT_FILE_FILTER
        )
        if not output_path:
            return

        trackers = [self.trackers_list.item(i).text() for i in range(self.trackers_list.count())]
        try:
            create_torrent_file(
                self._source_path,
                output_path,
                trackers,
                private=self.private_checkbox.isChecked(),
                comment=self.comment_input.text().strip(),
            )
        except Exception as exc:
            logger.warning("Torrent creation from %s to %s failed: %s", self._source_path, output_path, exc)
            QMessageBox.warning(self, tr("create_torrent.error_title"), tr("create_torrent.error_message"))
            return

        QMessageBox.information(
            self, tr("create_torrent.success_title"), tr("create_torrent.success_message", path=output_path)
        )
        self.accept()
