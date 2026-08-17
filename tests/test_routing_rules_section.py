import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from torrent2000.config.settings import Settings
from torrent2000.engine.routing_rules import RoutingRule
from torrent2000.ui.widgets import routing_rules_section as section_module
from torrent2000.ui.widgets.routing_rules_section import RoutingRulesSection


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))


class _FakeDialog:
    """Stand-in for _RoutingRuleDialog: skips actually opening a QDialog and
    just hands back a canned RoutingRule on exec()."""

    def __init__(self, rule: RoutingRule, accepted: bool = True) -> None:
        self._rule = rule
        self._accepted = accepted

    def exec(self):
        return QDialog.Accepted if self._accepted else QDialog.Rejected

    def result_rule(self) -> RoutingRule:
        return self._rule


def _section() -> RoutingRulesSection:
    return RoutingRulesSection(Settings(), MagicMock())


def test_starts_with_no_rules_and_management_buttons_disabled():
    section = _section()

    assert section.table.rowCount() == 0
    assert section.edit_button.isEnabled() is False
    assert section.delete_button.isEnabled() is False
    assert section.move_up_button.isEnabled() is False
    assert section.move_down_button.isEnabled() is False


def test_add_button_saves_the_rule_from_the_dialog_and_refreshes_the_table(monkeypatch):
    section = _section()
    new_rule = RoutingRule(name="Linux ISOs", pattern="ubuntu", match_field="name", destination="D:/linux")
    monkeypatch.setattr(
        section_module, "_RoutingRuleDialog", lambda existing=None, parent=None: _FakeDialog(new_rule)
    )

    section._on_add_clicked()

    assert [r.name for r in section._store.list_rules()] == ["Linux ISOs"]
    assert section.table.rowCount() == 1
    assert section.table.item(0, 0).text() == "Linux ISOs"
    assert section.table.item(0, 3).text() == "D:/linux"
    assert section.edit_button.isEnabled() is True


def test_add_button_does_nothing_when_dialog_is_cancelled(monkeypatch):
    section = _section()
    monkeypatch.setattr(
        section_module,
        "_RoutingRuleDialog",
        lambda existing=None, parent=None: _FakeDialog(
            RoutingRule(name="x", pattern="x", match_field="name", destination="x"), accepted=False
        ),
    )

    section._on_add_clicked()

    assert section._store.list_rules() == []
    assert section.table.rowCount() == 0


def test_edit_button_replaces_the_selected_rule(monkeypatch):
    section = _section()
    section._store.save_rule(RoutingRule(name="r1", pattern="old", match_field="name", destination="D:/old"))
    section._refresh_table()
    section.table.selectRow(0)

    edited = RoutingRule(name="r1", pattern="new", match_field="tracker", destination="D:/new")
    monkeypatch.setattr(
        section_module, "_RoutingRuleDialog", lambda existing=None, parent=None: _FakeDialog(edited)
    )

    section._on_edit_clicked()

    rules = section._store.list_rules()
    assert len(rules) == 1
    assert rules[0].pattern == "new"
    assert rules[0].destination == "D:/new"
    assert rules[0].match_field == "tracker"


def test_delete_button_removes_rule_after_confirmation(monkeypatch):
    section = _section()
    section._store.save_rule(RoutingRule(name="r1", pattern="x", match_field="name", destination="D:/x"))
    section._refresh_table()
    section.table.selectRow(0)

    monkeypatch.setattr(section_module.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    section._on_delete_clicked()

    assert section._store.list_rules() == []
    assert section.table.rowCount() == 0


def test_delete_button_declined_confirmation_keeps_the_rule(monkeypatch):
    section = _section()
    section._store.save_rule(RoutingRule(name="r1", pattern="x", match_field="name", destination="D:/x"))
    section._refresh_table()
    section.table.selectRow(0)

    monkeypatch.setattr(section_module.QMessageBox, "question", lambda *a, **k: QMessageBox.No)

    section._on_delete_clicked()

    assert [r.name for r in section._store.list_rules()] == ["r1"]


def test_move_down_then_up_round_trips_the_evaluation_order():
    section = _section()
    section._store.save_rule(RoutingRule(name="r1", pattern="x", match_field="name", destination="D:/1"))
    section._store.save_rule(RoutingRule(name="r2", pattern="x", match_field="name", destination="D:/2"))
    section._refresh_table()

    section.table.selectRow(0)  # r1
    section._on_move_down_clicked()

    assert [r.name for r in section._store.list_rules()] == ["r2", "r1"]
    assert [section.table.item(row, 0).text() for row in range(2)] == ["r2", "r1"]

    # r1 is now at row 1 (selection follows the moved row) -- move it back up.
    section._on_move_up_clicked()

    assert [r.name for r in section._store.list_rules()] == ["r1", "r2"]


def test_move_up_at_the_top_row_is_a_no_op():
    section = _section()
    section._store.save_rule(RoutingRule(name="r1", pattern="x", match_field="name", destination="D:/1"))
    section._store.save_rule(RoutingRule(name="r2", pattern="x", match_field="name", destination="D:/2"))
    section._refresh_table()
    section.table.selectRow(0)  # already at the top

    section._on_move_up_clicked()  # must not raise, must not change the order

    assert [r.name for r in section._store.list_rules()] == ["r1", "r2"]


def test_write_to_does_nothing():
    section = _section()
    section._store.save_rule(RoutingRule(name="r1", pattern="x", match_field="name", destination="D:/1"))
    other_settings = Settings()
    other_settings.default_download_dir = "untouched"

    section.write_to(other_settings)

    assert other_settings.default_download_dir == "untouched"
