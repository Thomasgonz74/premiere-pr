"""Regression tests for TetrisProgressWidget accessible name/description."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from torrent2000.i18n.translator import tr
from torrent2000.ui.widgets.tetris_progress import TetrisProgressWidget


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_initial_accessible_info_is_set_before_first_progress_update():
    widget = TetrisProgressWidget()

    assert widget.accessibleName() != ""
    assert widget.accessibleName() == tr("downloads_tab.column_progress")
    assert "0%" in widget.accessibleDescription()


def test_set_progress_updates_accessible_name_and_description():
    widget = TetrisProgressWidget()

    widget.set_progress(0.42)

    assert widget.accessibleName() != ""
    assert widget.accessibleName() == tr("downloads_tab.column_progress")
    assert "42" in widget.accessibleDescription()
