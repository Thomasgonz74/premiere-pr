"""Post-start file inclusion/exclusion editor.

add_tab.py already lets the user exclude files before a torrent starts (via
FileTreeRiskWidget, in-place in the Add tab). This dialog is the equivalent
for a torrent that is already running -- a file excluded by mistake (or on
purpose, and now wanted back) can only be recovered here. It is opened by
downloads_tab.py from a "Modifier les fichiers..." context menu entry; this
module does not wire itself into any menu.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from torrent2000.engine.session_manager import SessionManager
from torrent2000.i18n.translator import tr
from torrent2000.utils.formatting import human_size


class FilePriorityDialog(QDialog):
    """Every file starts checked -- SessionManager doesn't expose per-file
    priorities for reading (only get_torrent_files(), which has no priority
    field), so "currently excluded" can't be pre-computed from an already-
    running torrent. Save writes whatever is left unchecked as the new full
    exclusion set via set_file_priorities(), which also re-includes anything
    the user re-checks."""

    def __init__(self, session_manager: SessionManager, info_hash: str, parent=None) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._info_hash = info_hash
        self._files = session_manager.get_torrent_files(info_hash)

        self.setWindowTitle(tr("file_priority_dialog.window_title"))
        self.resize(480, 420)

        layout = QVBoxLayout(self)

        self.info_label = QLabel(self)
        self.info_label.setWordWrap(True)
        self.info_label.setVisible(False)
        layout.addWidget(self.info_label)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(2)
        self._apply_header_labels()
        self.tree.setRootIsDecorated(False)
        self.tree.header().setStretchLastSection(True)
        layout.addWidget(self.tree, 1)

        selection_row = QHBoxLayout()
        self.check_all_button = QPushButton(tr("file_priority_dialog.check_all"), self)
        self.check_all_button.clicked.connect(self._check_all)
        selection_row.addWidget(self.check_all_button)
        self.uncheck_all_button = QPushButton(tr("file_priority_dialog.uncheck_all"), self)
        self.uncheck_all_button.clicked.connect(self._uncheck_all)
        selection_row.addWidget(self.uncheck_all_button)
        selection_row.addStretch(1)
        layout.addLayout(selection_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.save_button = QPushButton(tr("file_priority_dialog.save_button"), self)
        self.save_button.clicked.connect(self._on_save_clicked)
        button_row.addWidget(self.save_button)
        self.cancel_button = QPushButton(tr("file_priority_dialog.cancel_button"), self)
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self._populate()

    def _apply_header_labels(self) -> None:
        self.tree.setHeaderLabels([tr("file_priority_dialog.column_file"), tr("file_priority_dialog.column_size")])

    def _populate(self) -> None:
        self.tree.clear()
        if not self._files:
            # No handle, or metadata not received yet (magnet still resolving)
            # -- get_torrent_files() returns [] in both cases.
            self.info_label.setText(tr("file_priority_dialog.no_metadata_message"))
            self.info_label.setVisible(True)
            self.tree.setVisible(False)
            self.check_all_button.setEnabled(False)
            self.uncheck_all_button.setEnabled(False)
            self.save_button.setEnabled(False)
            return
        if len(self._files) == 1:
            # Unchecking the only file would exclude the entire torrent --
            # worth calling out rather than letting it happen silently.
            self.info_label.setText(tr("file_priority_dialog.single_file_message"))
            self.info_label.setVisible(True)
        for entry in self._files:
            item = QTreeWidgetItem([entry.path, human_size(entry.size)])
            item.setData(0, Qt.UserRole, entry.index)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked)
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)

    def _check_all(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.Checked)

    def _uncheck_all(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.Unchecked)

    def _excluded_indices(self) -> set[int]:
        excluded = set()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.Unchecked:
                excluded.add(item.data(0, Qt.UserRole))
        return excluded

    def _on_save_clicked(self) -> None:
        self._session_manager.set_file_priorities(self._info_hash, self._excluded_indices())
        self.accept()
