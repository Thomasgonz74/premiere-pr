"""Regression coverage for the confirmed screenshot bug: shrinking the
window to its minimum size overlapped 'Lien magnet:' onto the drop zone and
overflowed the "Créer un torrent..." button's own text past its frame.

Root cause (see frameless_resize.py/add_tab.py comments): this window is
frameless, so drag-to-resize is our own code (FramelessResizeController),
floored only by MIN_WINDOW_SIZE -- not by Qt's automatic layout-minimum
enforcement. AddTorrentTab had no QScrollArea (unlike ProfileTab), so its
real minimumSizeHint (~514px tall pre-fix) exceeded the old hardcoded
MIN_WINDOW_SIZE height (420), and forcing the window below what its own
layout needs is exactly when Qt can produce overlapping child geometries.
The fix adds a QScrollArea (matching ProfileTab's existing pattern) and
computes the window's real minimum from actual chrome content instead of a
guessed constant (see frameless_resize.compute_min_window_size).
"""

import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QScrollArea

from torrent2000.config.settings import Settings
from torrent2000.ui.main_window import MainWindow


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    win = MainWindow(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        Settings(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
    )
    # Drive it down to the app's own real minimum -- exactly the scenario
    # from the bug report ("en redimensionnant la fenetre vers sa taille
    # minimale"). QWidget.resize() on a top-level window clamps to
    # setMinimumSize() on its own, so this lands exactly at the floor.
    win.resize(win.minimumWidth(), win.minimumHeight())
    win.show()
    QApplication.processEvents()
    yield win
    win.close()


def _descendant_widgets(widget):
    for child in widget.children():
        if hasattr(child, "geometry") and hasattr(child, "isVisible"):
            yield child
            # A QScrollArea's whole point is letting its content widget be
            # taller/wider than the visible viewport -- that's scrolling,
            # not the overlap bug this test guards against, so don't
            # recurse into what it scrolls.
            if not isinstance(child, QScrollArea):
                yield from _descendant_widgets(child)


def test_add_tab_fits_within_the_apps_real_minimum_window_size(window):
    """AddTorrentTab is now wrapped in a QScrollArea, so its own
    minimumSizeHint must be small enough to always fit inside the window's
    real (content-derived) minimum -- unlike downloads/share/rss, whose
    wide tables are allowed to exceed it since QTableWidget scrolls
    horizontally instead of overlapping."""
    add_tab = window._add_tab
    hint = add_tab.minimumSizeHint()
    assert hint.width() <= window.minimumWidth()
    assert hint.height() <= window.minimumHeight()


def test_no_visible_widget_overflows_its_parent_at_minimum_size(window):
    """Generic overlap/overflow guard: at the real minimum window size, no
    visible widget's geometry should extend past its own parent's bounds."""
    add_tab = window._add_tab
    for child in _descendant_widgets(add_tab):
        if not child.isVisible():
            continue
        parent = child.parentWidget()
        if parent is None:
            continue
        assert parent.rect().contains(child.geometry()), (
            f"{child.objectName() or child} at {child.geometry()} overflows "
            f"its parent {parent.objectName() or parent} rect {parent.rect()}"
        )


def test_magnet_label_does_not_overlap_the_drop_zone(window):
    """The exact bug from the screenshot: 'Lien magnet:' overlapping the
    drop zone."""
    add_tab = window._add_tab
    source_box = add_tab.source_box
    label_rect = add_tab.magnet_label.geometry()
    label_rect.moveTopLeft(add_tab.magnet_label.mapTo(source_box, label_rect.topLeft()))
    drop_rect = add_tab.drop_zone.geometry()
    drop_rect.moveTopLeft(add_tab.drop_zone.mapTo(source_box, drop_rect.topLeft()))
    assert not label_rect.intersects(drop_rect)


def test_create_torrent_button_text_fits_within_its_own_frame(window):
    """The other half of the reported bug: the button's own text overflowing
    its frame because the button was squeezed narrower than its text."""
    button = window._add_tab.create_torrent_button
    text_width = button.fontMetrics().horizontalAdvance(button.text())
    assert button.width() >= text_width
