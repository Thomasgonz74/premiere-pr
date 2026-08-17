"""Regression tests for SpeedGraphWidget: set_history() must never crash
paintEvent, including the empty-history case (where the vertical scale
could otherwise divide by zero)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from torrent2000.ui.widgets.speed_graph import SpeedGraphWidget


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_empty_history_does_not_crash_paint():
    widget = SpeedGraphWidget()
    widget.resize(300, 150)

    widget.set_history([])
    pixmap = widget.grab()

    assert not pixmap.isNull()


def test_history_with_all_zero_samples_does_not_crash_paint():
    # Every sample at 0 bytes/sec is exactly the case where an unguarded
    # "scale to current max" would divide by zero.
    widget = SpeedGraphWidget()
    widget.resize(300, 150)

    widget.set_history([(0, 0)] * 20)
    pixmap = widget.grab()

    assert not pixmap.isNull()


def test_history_with_varying_samples_renders_without_raising():
    widget = SpeedGraphWidget()
    widget.resize(300, 150)

    samples = [(i * 1024, i * 512) for i in range(200)]
    widget.set_history(samples)
    pixmap = widget.grab()

    assert not pixmap.isNull()


def test_single_sample_does_not_crash_paint():
    # A single point can't form a line segment -- guards against a
    # count-1 division inside the curve-drawing step calculation.
    widget = SpeedGraphWidget()
    widget.resize(300, 150)

    widget.set_history([(4096, 2048)])
    pixmap = widget.grab()

    assert not pixmap.isNull()


def test_set_history_replaces_previous_data():
    widget = SpeedGraphWidget()
    widget.set_history([(100, 200)])
    assert widget._samples == [(100, 200)]

    widget.set_history([(300, 400), (500, 600)])
    assert widget._samples == [(300, 400), (500, 600)]
