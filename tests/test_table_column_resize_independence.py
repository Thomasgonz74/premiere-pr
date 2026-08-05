"""Regression guard for "dragging one column border moves a different one".

QHeaderView.Stretch on a column keeps the header's total width pinned to the
viewport width, so resizing ANY other Interactive column silently
compensates by shrinking/growing the Stretch column too. Net effect: drag
column N's border, its neighbor visibly moves, but the Stretch column (often
far away, e.g. the first "Name" column) also shifts -- which is exactly what
the user reported ("the opposite border moves, not the one I grabbed").
Every table now uses a fixed initial width + plain Interactive resizing for
column 0 instead, so resizing any column is fully independent of every
other one.
"""

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.config.settings import Settings
from torrent2000.ui.tabs.downloads_tab import DownloadsTab
from torrent2000.ui.tabs.rss_tab import RssTab
from torrent2000.ui.tabs.share_tab import ShareTab


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _resize_mode_of_every_column_is_never_stretch(table) -> bool:
    from PySide6.QtWidgets import QHeaderView

    header = table.horizontalHeader()
    return all(header.sectionResizeMode(i) != QHeaderView.Stretch for i in range(header.count()))


def _assert_resizing_one_column_does_not_move_others(table):
    header = table.horizontalHeader()
    widths_before = [header.sectionSize(i) for i in range(header.count())]
    target = 1 if header.count() > 1 else 0
    header.resizeSection(target, widths_before[target] + 40)
    widths_after = [header.sectionSize(i) for i in range(header.count())]
    for i in range(header.count()):
        if i == target:
            assert widths_after[i] == widths_before[i] + 40
        else:
            assert widths_after[i] == widths_before[i], f"column {i} moved when only column {target} was resized"


def test_downloads_tab_table_has_no_stretch_column():
    tab = DownloadsTab(MagicMock())
    assert _resize_mode_of_every_column_is_never_stretch(tab.table)
    _assert_resizing_one_column_does_not_move_others(tab.table)


def test_share_tab_table_has_no_stretch_column():
    sm = MagicMock()
    sls = MagicMock()
    sls.tracked_info_hashes.return_value = []
    tab = ShareTab(sm, sls, Settings())
    assert _resize_mode_of_every_column_is_never_stretch(tab.table)
    _assert_resizing_one_column_does_not_move_others(tab.table)


def test_rss_tab_table_has_no_stretch_column():
    sm = MagicMock()
    feed_service = MagicMock()
    settings = Settings()
    tab = RssTab(sm, feed_service, settings)
    assert _resize_mode_of_every_column_is_never_stretch(tab.table)
    _assert_resizing_one_column_does_not_move_others(tab.table)
