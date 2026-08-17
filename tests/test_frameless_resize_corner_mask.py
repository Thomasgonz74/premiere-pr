import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from torrent2000.ui.frameless_resize import FramelessResizeController


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller():
    window = QWidget()
    central = QWidget(window)
    window.resize(300, 200)
    ctrl = FramelessResizeController(window, central)
    yield ctrl
    window.close()
    window.deleteLater()
    QApplication.processEvents()


def test_update_corner_mask_sets_non_empty_mask_matching_window_bounds(controller):
    controller.set_corner_radius(12)

    mask = controller._window.mask()
    assert not mask.isEmpty()
    assert mask.boundingRect() == controller._window.rect()


def test_update_corner_mask_clears_mask_when_radius_is_zero(controller):
    controller.set_corner_radius(12)
    controller.set_corner_radius(0)

    assert controller._window.mask().isEmpty()
