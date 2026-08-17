"""Profile tab section for engine/routing_rules.py -- lets the user define an
ordered list of "if the name/tracker contains X, use folder Y" rules that
ui/tabs/add_tab.py, engine/rss_feed_service.py, and
engine/watch_folder_service.py each consult to resolve a torrent's
destination folder before it is ever added, instead of always falling back
to the single default download directory.

Follows the section pattern documented at the top of
ui/tabs/profile_sections.py, with the same live-apply-only convention as
settings_profiles_section.py: every action here (add/edit/delete/reorder)
persists immediately through RoutingRuleStore, so write_to() has nothing
left to do.
"""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from torrent2000.config.settings import Settings
from torrent2000.engine.routing_rules import RoutingRule, RoutingRuleStore
from torrent2000.engine.session_manager import SessionManager
from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.table_helpers import configure_no_stretch_table


def _columns() -> list[str]:
    return [
        tr("routing_rules.column_name"),
        tr("routing_rules.column_pattern"),
        tr("routing_rules.column_field"),
        tr("routing_rules.column_destination"),
    ]


def _field_label(match_field: str) -> str:
    return tr("routing_rules.field_tracker") if match_field == "tracker" else tr("routing_rules.field_name")


class _RoutingRuleDialog(QDialog):
    """Small add/edit form: rule name, pattern, name-vs-tracker field, and a
    destination folder. A transient, opened-fresh-each-time dialog -- like
    CreateTorrentDialog/FilePriorityDialog/SpeedGraphDialog -- so it has no
    retranslate_ui(), since it's never kept alive across a language switch."""

    def __init__(self, existing: RoutingRule | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("routing_rules.dialog_edit_title" if existing else "routing_rules.dialog_add_title"))

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.name_input = QLineEdit(self)
        form.addRow(tr("routing_rules.name_label"), self.name_input)

        self.pattern_input = QLineEdit(self)
        form.addRow(tr("routing_rules.pattern_label"), self.pattern_input)

        self.field_combo = QComboBox(self)
        self.field_combo.addItem(tr("routing_rules.field_name"), "name")
        self.field_combo.addItem(tr("routing_rules.field_tracker"), "tracker")
        form.addRow(tr("routing_rules.field_label"), self.field_combo)

        dest_row = QHBoxLayout()
        self.destination_input = QLineEdit(self)
        dest_row.addWidget(self.destination_input, 1)
        self.browse_button = QPushButton(tr("common.browse"), self)
        self.browse_button.clicked.connect(self._on_browse_clicked)
        dest_row.addWidget(self.browse_button)
        form.addRow(tr("routing_rules.destination_label"), dest_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.save_button = QPushButton(tr("routing_rules.dialog_save_button"), self)
        self.save_button.clicked.connect(self._on_save_clicked)
        button_row.addWidget(self.save_button)
        self.cancel_button = QPushButton(tr("common.cancel"), self)
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        if existing is not None:
            self.name_input.setText(existing.name)
            self.pattern_input.setText(existing.pattern)
            idx = self.field_combo.findData(existing.match_field)
            self.field_combo.setCurrentIndex(max(0, idx))
            self.destination_input.setText(existing.destination)

    def _on_browse_clicked(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, tr("routing_rules.choose_dest_title"), self.destination_input.text()
        )
        if directory:
            self.destination_input.setText(directory)

    def _on_save_clicked(self) -> None:
        if not self.name_input.text().strip() or not self.pattern_input.text().strip() or not self.destination_input.text().strip():
            QMessageBox.information(
                self, tr("routing_rules.missing_fields_title"), tr("routing_rules.missing_fields_message")
            )
            return
        self.accept()

    def result_rule(self) -> RoutingRule:
        return RoutingRule(
            name=self.name_input.text().strip(),
            pattern=self.pattern_input.text().strip(),
            match_field=self.field_combo.currentData(),
            destination=self.destination_input.text().strip(),
        )


class RoutingRulesSection(QGroupBox):
    """List/add/edit/delete/reorder RoutingRule entries (see
    engine/routing_rules.py). Rules are evaluated top-to-bottom by the three
    callers that consult them, so Monter/Descendre here directly controls
    priority, not just display order."""

    def __init__(self, settings: Settings, session_manager: SessionManager, parent=None) -> None:
        super().__init__(tr("routing_rules.group"), parent)
        self._settings = settings
        # Accepted for the same constructor shape as sibling *_section
        # classes (SettingsProfilesSection, RemoteAccessSection) even though
        # this section has no live session-manager action of its own -- every
        # routing decision happens later, in the three callers that read
        # RoutingRuleStore directly (add_tab.py, rss_feed_service.py,
        # watch_folder_service.py), not here.
        self._session_manager = session_manager
        self._store = RoutingRuleStore()

        layout = QVBoxLayout(self)

        self.intro_label = QLabel(tr("routing_rules.intro"), self)
        self.intro_label.setWordWrap(True)
        layout.addWidget(self.intro_label)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(_columns())
        configure_no_stretch_table(self.table, 160)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        button_row = QHBoxLayout()
        self.add_button = QPushButton(tr("common.add"), self)
        self.add_button.clicked.connect(self._on_add_clicked)
        button_row.addWidget(self.add_button)
        self.edit_button = QPushButton(tr("routing_rules.edit_button"), self)
        self.edit_button.clicked.connect(self._on_edit_clicked)
        button_row.addWidget(self.edit_button)
        self.delete_button = QPushButton(tr("common.remove"), self)
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._on_delete_clicked)
        button_row.addWidget(self.delete_button)
        self.move_up_button = QPushButton(tr("routing_rules.move_up_button"), self)
        self.move_up_button.clicked.connect(self._on_move_up_clicked)
        button_row.addWidget(self.move_up_button)
        self.move_down_button = QPushButton(tr("routing_rules.move_down_button"), self)
        self.move_down_button.clicked.connect(self._on_move_down_clicked)
        button_row.addWidget(self.move_down_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._refresh_table()

    def retranslate_ui(self) -> None:
        self.setTitle(tr("routing_rules.group"))
        self.intro_label.setText(tr("routing_rules.intro"))
        self.add_button.setText(tr("common.add"))
        self.edit_button.setText(tr("routing_rules.edit_button"))
        self.delete_button.setText(tr("common.remove"))
        self.move_up_button.setText(tr("routing_rules.move_up_button"))
        self.move_down_button.setText(tr("routing_rules.move_down_button"))
        self.table.setHorizontalHeaderLabels(_columns())
        self._refresh_table()  # re-renders the field column's "Nom"/"Tracker" label in the new language

    def write_to(self, settings: Settings) -> None:
        pass  # every action here already applies and persists immediately

    # ---------------------------------------------------------------- table

    def _refresh_table(self, select_name: str | None = None) -> None:
        rules = self._store.list_rules()
        self.table.setRowCount(0)
        for rule in rules:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(rule.name))
            self.table.setItem(row, 1, QTableWidgetItem(rule.pattern))
            self.table.setItem(row, 2, QTableWidgetItem(_field_label(rule.match_field)))
            dest_item = QTableWidgetItem(rule.destination)
            dest_item.setToolTip(rule.destination)
            self.table.setItem(row, 3, dest_item)
        if select_name is not None:
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).text() == select_name:
                    self.table.selectRow(row)
                    break

        has_rules = self.table.rowCount() > 0
        self.edit_button.setEnabled(has_rules)
        self.delete_button.setEnabled(has_rules)
        self.move_up_button.setEnabled(has_rules)
        self.move_down_button.setEnabled(has_rules)

    def _selected_rule_name(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.text() if item is not None else None

    def _rule_names_in_order(self) -> list[str]:
        return [self.table.item(row, 0).text() for row in range(self.table.rowCount())]

    # -------------------------------------------------------------- actions

    def _on_add_clicked(self) -> None:
        dialog = _RoutingRuleDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            rule = dialog.result_rule()
            self._store.save_rule(rule)
            self._refresh_table(select_name=rule.name)

    def _on_edit_clicked(self) -> None:
        name = self._selected_rule_name()
        if name is None:
            return
        existing = next((r for r in self._store.list_rules() if r.name == name), None)
        if existing is None:
            return
        dialog = _RoutingRuleDialog(existing=existing, parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_rule = dialog.result_rule()
            if new_rule.name != existing.name:
                # Renamed: drop the old entry first so it isn't left behind
                # alongside the new one under a different name.
                self._store.delete(existing.name)
            self._store.save_rule(new_rule)
            self._refresh_table(select_name=new_rule.name)

    def _on_delete_clicked(self) -> None:
        name = self._selected_rule_name()
        if name is None:
            return
        reply = QMessageBox.question(
            self,
            tr("routing_rules.delete_confirm_title"),
            tr("routing_rules.delete_confirm_message", name=name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._store.delete(name)
        self._refresh_table()

    def _on_move_up_clicked(self) -> None:
        row = self.table.currentRow()
        if row <= 0:
            return
        names = self._rule_names_in_order()
        names[row - 1], names[row] = names[row], names[row - 1]
        self._store.reorder(names)
        self._refresh_table(select_name=names[row - 1])

    def _on_move_down_clicked(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount() - 1:
            return
        names = self._rule_names_in_order()
        names[row + 1], names[row] = names[row], names[row + 1]
        self._store.reorder(names)
        self._refresh_table(select_name=names[row + 1])
