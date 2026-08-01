from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrent2000.engine.torrent_item import TrackerInfo

COLUMNS = ["URL", "Tier", "Dernière erreur", "Action"]


class TrackerEditorWidget(QWidget):
    """Manual, transparent tracker list editor -- add/remove a tracker at any
    time via a button, exactly like qBittorrent/Deluge already offer. No
    timers, no automation tied to download progress."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._info_hash: str | None = None
        self._session_manager = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.table)

        add_row = QHBoxLayout()
        self.url_input = QLineEdit(self)
        self.url_input.setPlaceholderText("http://tracker.example.com/announce")
        add_row.addWidget(self.url_input)
        self.add_button = QPushButton("Ajouter", self)
        self.add_button.clicked.connect(self._on_add_clicked)
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)

    def bind(self, session_manager, info_hash: str | None) -> None:
        self._session_manager = session_manager
        self._info_hash = info_hash
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        if self._session_manager is None or self._info_hash is None:
            return
        trackers: list[TrackerInfo] = self._session_manager.get_trackers(self._info_hash)
        self.table.setRowCount(len(trackers))
        for row, tracker in enumerate(trackers):
            self.table.setItem(row, 0, QTableWidgetItem(tracker.url))
            self.table.setItem(row, 1, QTableWidgetItem(str(tracker.tier)))
            self.table.setItem(row, 2, QTableWidgetItem(tracker.last_error))

            remove_button = QPushButton("Retirer", self.table)
            remove_button.setObjectName("dangerButton")
            remove_button.clicked.connect(lambda checked=False, url=tracker.url: self._on_remove_row_clicked(url))
            self.table.setCellWidget(row, 3, remove_button)

    def _on_add_clicked(self) -> None:
        url = self.url_input.text().strip()
        if not url or self._session_manager is None or self._info_hash is None:
            return
        self._session_manager.add_tracker(self._info_hash, url)
        self.url_input.clear()
        self.refresh()

    def _on_remove_row_clicked(self, url: str) -> None:
        if self._session_manager is None or self._info_hash is None:
            return
        self._session_manager.remove_tracker(self._info_hash, url)
        self.refresh()
