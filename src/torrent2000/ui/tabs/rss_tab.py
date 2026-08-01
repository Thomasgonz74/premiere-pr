from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from torrent2000.config.settings import RssFeedSubscription, Settings
from torrent2000.engine.rss_feed_service import RssFeedService
from torrent2000.engine.session_manager import SessionManager

COLUMNS = ["Flux RSS", "Mot-clé", "Actif", "Action"]
MAX_LOG_ENTRIES = 200


class RssTab(QWidget):
    """Subscribe to RSS feeds and auto-download new matching items -- see
    engine/rss_feed_service.py for the periodic check/fetch/add logic this
    tab configures and reports on."""

    def __init__(
        self,
        session_manager: SessionManager,
        rss_feed_service: RssFeedService,
        settings: Settings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_manager = session_manager
        self._rss_feed_service = rss_feed_service
        self._settings = settings

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Abonnements RSS", self))
        top_row.addStretch(1)
        self.check_now_button = QPushButton("Vérifier maintenant", self)
        self.check_now_button.clicked.connect(self._rss_feed_service.check_now)
        top_row.addWidget(self.check_now_button)
        layout.addLayout(top_row)

        add_box = QGroupBox("Ajouter un flux", self)
        add_layout = QVBoxLayout(add_box)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("URL du flux:", add_box))
        self.url_input = QLineEdit(add_box)
        self.url_input.setPlaceholderText("https://exemple.com/rss")
        url_row.addWidget(self.url_input, 1)
        add_layout.addLayout(url_row)

        keyword_row = QHBoxLayout()
        keyword_row.addWidget(QLabel("Mot-clé (filtre):", add_box))
        self.keyword_input = QLineEdit(add_box)
        self.keyword_input.setPlaceholderText("laisser vide pour tout télécharger")
        keyword_row.addWidget(self.keyword_input, 1)
        add_layout.addLayout(keyword_row)

        add_button_row = QHBoxLayout()
        add_button_row.addStretch(1)
        self.add_button = QPushButton("Ajouter", add_box)
        self.add_button.clicked.connect(self._on_add_clicked)
        add_button_row.addWidget(self.add_button)
        add_layout.addLayout(add_button_row)

        layout.addWidget(add_box)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 2)

        log_box = QGroupBox("Éléments récemment ajoutés", self)
        log_layout = QVBoxLayout(log_box)
        self.log_list = QListWidget(log_box)
        log_layout.addWidget(self.log_list)
        layout.addWidget(log_box, 1)

        self._rss_feed_service.items_found.connect(self._on_items_found)
        self._rss_feed_service.feed_check_failed.connect(self._on_feed_check_failed)

        self._refresh_table()

    # ------------------------------------------------------------------ add

    def _on_add_clicked(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.information(self, "URL manquante", "Saisissez l'URL du flux RSS à ajouter.")
            return

        keyword = self.keyword_input.text().strip()
        self._settings.rss_feeds.append(RssFeedSubscription(url=url, filter_keyword=keyword, enabled=True))
        self._settings.save()

        self.url_input.clear()
        self.keyword_input.clear()
        self._refresh_table()

    # ---------------------------------------------------------------- table

    def _refresh_table(self) -> None:
        self.table.setRowCount(0)
        for feed in self._settings.rss_feeds:
            self._add_row(feed)

    def _add_row(self, feed: RssFeedSubscription) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(feed.url))
        self.table.setItem(row, 1, QTableWidgetItem(feed.filter_keyword))

        enabled_container = QWidget(self.table)
        enabled_layout = QHBoxLayout(enabled_container)
        enabled_layout.setContentsMargins(0, 0, 0, 0)
        enabled_layout.setAlignment(Qt.AlignCenter)
        enabled_checkbox = QCheckBox(enabled_container)
        enabled_checkbox.setChecked(feed.enabled)
        enabled_checkbox.toggled.connect(lambda checked, f=feed: self._on_enabled_toggled(f, checked))
        enabled_layout.addWidget(enabled_checkbox)
        self.table.setCellWidget(row, 2, enabled_container)

        remove_button = QPushButton("Retirer", self.table)
        remove_button.setObjectName("dangerButton")
        remove_button.clicked.connect(lambda checked=False, f=feed: self._on_remove_clicked(f))
        self.table.setCellWidget(row, 3, remove_button)

    def _on_enabled_toggled(self, feed: RssFeedSubscription, checked: bool) -> None:
        feed.enabled = checked
        self._settings.save()

    def _on_remove_clicked(self, feed: RssFeedSubscription) -> None:
        # Identity-based removal (not `list.remove`/`in`, which would compare
        # by value): RssFeedSubscription is a dataclass with value equality,
        # so two subscriptions with identical url/keyword/enabled would
        # otherwise be indistinguishable and the wrong row's entry could be
        # dropped.
        for i, existing in enumerate(self._settings.rss_feeds):
            if existing is feed:
                del self._settings.rss_feeds[i]
                self._settings.save()
                break
        self._refresh_table()

    # ---------------------------------------------------------------- log

    def _on_items_found(self, feed_url: str, items: list) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        for item in items:
            title = item.get("title") or feed_url
            self.log_list.insertItem(0, f"[{timestamp}] {title} -- {feed_url}")
        while self.log_list.count() > MAX_LOG_ENTRIES:
            self.log_list.takeItem(self.log_list.count() - 1)

    def _on_feed_check_failed(self, feed_url: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_list.insertItem(0, f"[{timestamp}] Échec: {feed_url} ({message})")
        while self.log_list.count() > MAX_LOG_ENTRIES:
            self.log_list.takeItem(self.log_list.count() - 1)
