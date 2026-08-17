"""Regression tests for TetrisProgressWidget's shared animation timer.

TetrisProgressWidget used to own one QTimer per instance; N active download
rows meant N independent 150ms timers. It now shares a single QTimer across
every currently-alive instance (tracked via a `weakref.WeakSet`), driving
all of their animation ticks from one place.
"""

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from torrent2000.ui.widgets.tetris_progress import TetrisProgressWidget


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _reset_shared_timer_state():
    """Start (and leave) each test with no leftover shared-timer state, so
    tests in this file -- and other test modules run in the same session --
    don't interfere with each other."""

    def _reset():
        gc.collect()
        TetrisProgressWidget._instances.clear()
        if TetrisProgressWidget._shared_timer is not None:
            TetrisProgressWidget._shared_timer.stop()
            TetrisProgressWidget._shared_timer = None

    _reset()
    yield
    _reset()


def test_multiple_widgets_share_one_underlying_timer_instance():
    widgets = [TetrisProgressWidget() for _ in range(5)]

    assert len(TetrisProgressWidget._instances) == 5
    shared_timer = TetrisProgressWidget._shared_timer
    assert shared_timer is not None

    # Every widget's registration re-uses the same QTimer object -- it is
    # never recreated for the 2nd..Nth widget.
    for widget in widgets:
        assert widget in TetrisProgressWidget._instances
    assert TetrisProgressWidget._shared_timer is shared_timer

    del widgets


def test_manual_tick_advances_every_live_instance():
    widgets = [TetrisProgressWidget() for _ in range(3)]
    for widget in widgets:
        widget.set_progress(1.0)

    before = [w.model.filled_count for w in widgets]
    assert before == [0, 0, 0]

    TetrisProgressWidget._on_shared_tick()

    after = [w.model.filled_count for w in widgets]
    # A single shared tick must advance *every* live widget's model, not
    # just one of them.
    assert all(a > b for a, b in zip(after, before))

    del widgets


def test_ticking_does_not_touch_widgets_below_their_target():
    below_target, at_target = TetrisProgressWidget(), TetrisProgressWidget()
    at_target.set_progress(0.0)  # target == filled_count == 0 already
    below_target.set_progress(0.5)

    changed = TetrisProgressWidget._on_shared_tick()

    assert at_target.model.filled_count == 0
    assert below_target.model.filled_count > 0
    assert changed is None  # _on_shared_tick has no return value contract

    del below_target, at_target


def test_no_timer_left_running_after_all_instances_are_dereferenced():
    widgets = [TetrisProgressWidget() for _ in range(4)]
    assert TetrisProgressWidget._shared_timer is not None
    assert len(TetrisProgressWidget._instances) == 4

    del widgets
    gc.collect()

    assert len(TetrisProgressWidget._instances) == 0

    # The shared timer notices instances are gone and tears itself down the
    # next time it ticks -- simulate that tick here rather than waiting on
    # a real 150ms Qt event-loop cycle.
    TetrisProgressWidget._on_shared_tick()

    assert TetrisProgressWidget._shared_timer is None


def test_a_new_widget_after_teardown_starts_a_fresh_shared_timer():
    widgets = [TetrisProgressWidget()]
    del widgets
    gc.collect()
    TetrisProgressWidget._on_shared_tick()
    assert TetrisProgressWidget._shared_timer is None

    widget = TetrisProgressWidget()

    assert TetrisProgressWidget._shared_timer is not None
    assert widget in TetrisProgressWidget._instances

    del widget
