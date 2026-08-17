from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
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
from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.table_helpers import configure_no_stretch_table, make_remove_button

MAX_LOG_ENTRIES = 200


def _columns() -> list[str]:
    return [
        tr("rss_tab.column_feed"),
        tr("rss_tab.column_keyword"),
        tr("rss_tab.column_active"),
        tr("rss_tab.column_action"),
    ]


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
        self._filter_text: str = ""

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.subscriptions_label = QLabel(tr("rss_tab.subscriptions"), self)
        top_row.addWidget(self.subscriptions_label)
        top_row.addStretch(1)
        self.check_now_button = QPushButton(tr("rss_tab.check_now"), self)
        self.check_now_button.clicked.connect(self._rss_feed_service.check_now)
        top_row.addWidget(self.check_now_button)
        layout.addLayout(top_row)

        self.add_box = QGroupBox(tr("rss_tab.add_feed_group"), self)
        add_layout = QVBoxLayout(self.add_box)

        url_row = QHBoxLayout()
        self.url_label = QLabel(tr("rss_tab.feed_url_label"), self.add_box)
        url_row.addWidget(self.url_label)
        self.url_input = QLineEdit(self.add_box)
        self.url_input.setPlaceholderText("https://exemple.com/rss")
        url_row.addWidget(self.url_input, 1)
        add_layout.addLayout(url_row)

        keyword_row = QHBoxLayout()
        self.keyword_label = QLabel(tr("rss_tab.keyword_label"), self.add_box)
        keyword_row.addWidget(self.keyword_label)
        self.keyword_input = QLineEdit(self.add_box)
        self.keyword_input.setPlaceholderText(tr("rss_tab.keyword_placeholder"))
        keyword_row.addWidget(self.keyword_input, 1)
        add_layout.addLayout(keyword_row)

        add_button_row = QHBoxLayout()
        add_button_row.addStretch(1)
        self.add_button = QPushButton(tr("common.add"), self.add_box)
        self.add_button.clicked.connect(self._on_add_clicked)
        add_button_row.addWidget(self.add_button)
        add_layout.addLayout(add_button_row)

        layout.addWidget(self.add_box)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(tr("common.search_placeholder"))
        self.search_input.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self.search_input)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(_columns())
        configure_no_stretch_table(self.table, 280)
        layout.addWidget(self.table, 2)

        self.log_box = QGroupBox(tr("rss_tab.log_group"), self)
        log_layout = QVBoxLayout(self.log_box)
        self.log_list = QListWidget(self.log_box)
        log_layout.addWidget(self.log_list)
        layout.addWidget(self.log_box, 1)

        self._rss_feed_service.items_found.connect(self._on_items_found)
        self._rss_feed_service.feed_check_failed.connect(self._on_feed_check_failed)

        self._refresh_table()

    # ----------------------------------------------------------- retranslate

    def retranslate_ui(self) -> None:
        self.subscriptions_label.setText(tr("rss_tab.subscriptions"))
        self.check_now_button.setText(tr("rss_tab.check_now"))
        self.add_box.setTitle(tr("rss_tab.add_feed_group"))
        self.url_label.setText(tr("rss_tab.feed_url_label"))
        self.keyword_label.setText(tr("rss_tab.keyword_label"))
        self.keyword_input.setPlaceholderText(tr("rss_tab.keyword_placeholder"))
        self.add_button.setText(tr("common.add"))
        self.search_input.setPlaceholderText(tr("common.search_placeholder"))
        self.table.setHorizontalHeaderLabels(_columns())
        self.log_box.setTitle(tr("rss_tab.log_group"))
        remove_label = tr("common.remove")
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 3)
            if widget is not None:
                widget.setText(remove_label)

    # ------------------------------------------------------------------ add

    def _on_add_clicked(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.information(self, tr("rss_tab.missing_url_title"), tr("rss_tab.missing_url_message"))
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
        self._apply_filter()

    def _add_row(self, feed: RssFeedSubscription) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(feed.url))
        self.table.item(row, 0).setToolTip(feed.url)
        self.table.setItem(row, 1, QTableWidgetItem(feed.filter_keyword))
        self.table.item(row, 1).setToolTip(feed.filter_keyword)

        enabled_container = QWidget(self.table)
        enabled_layout = QHBoxLayout(enabled_container)
        enabled_layout.setContentsMargins(0, 0, 0, 0)
        enabled_layout.setAlignment(Qt.AlignCenter)
        enabled_checkbox = QCheckBox(enabled_container)
        enabled_checkbox.setChecked(feed.enabled)
        enabled_checkbox.toggled.connect(lambda checked, f=feed: self._on_enabled_toggled(f, checked))
        enabled_layout.addWidget(enabled_checkbox)
        self.table.setCellWidget(row, 2, enabled_container)

        remove_button = make_remove_button(self.table, lambda f=feed: self._on_remove_clicked(f))
        self.table.setCellWidget(row, 3, remove_button)

    # ----------------------------------------------------------------- filter

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self._filter_text.strip().lower()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            url = item.text() if item is not None else ""
            self.table.setRowHidden(row, bool(needle) and needle not in url.lower())

    def _on_enabled_toggled(self, feed: RssFeedSubscription, checked: bool) -> None:
        # Live-apply (saved immediately), unlike RssTab's Add-a-feed form
        # above -- this is a single toggle on an already-saved subscription,
        # not a multi-field form to review before committing, so there's no
        # "Save" step to gate it behind. See profile_sections.py's module
        # docstring for this app's live-apply-vs-save-on-click convention.
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
        self.log_list.insertItem(0, f"[{timestamp}] {tr('rss_tab.check_failed', feed_url=feed_url, message=message)}")
        while self.log_list.count() > MAX_LOG_ENTRIES:
            self.log_list.takeItem(self.log_list.count() - 1)
