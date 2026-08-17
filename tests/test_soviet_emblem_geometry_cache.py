"""Regression tests for the hammer-and-sickle geometry cache.

Verifies that ``_cached_geometry`` actually memoizes (same object identity
for repeated calls with identical args, distinct objects for different
args) and that caching doesn't silently change the produced geometry --
the cached points must match a fresh, independent computation done by
calling the underlying geometry builders directly.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from torrent2000.ui.widgets.soviet_emblem import (
    _cached_geometry,
    _crescent_blade_path,
    _hammer_polygon,
    _sickle_handle_polygon,
)


def _ensure_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_cached_geometry_returns_same_objects_for_same_args():
    _ensure_qapp()
    _cached_geometry.cache_clear()

    hammer1, blade1, handle1 = _cached_geometry(10.0, 20.0, 30.0)
    hammer2, blade2, handle2 = _cached_geometry(10.0, 20.0, 30.0)

    assert hammer1 is hammer2
    assert blade1 is blade2
    assert handle1 is handle2


def test_cached_geometry_returns_distinct_objects_for_different_size():
    _ensure_qapp()
    _cached_geometry.cache_clear()

    hammer1, blade1, handle1 = _cached_geometry(10.0, 20.0, 30.0)
    hammer2, blade2, handle2 = _cached_geometry(10.0, 20.0, 31.0)

    assert hammer1 is not hammer2
    assert blade1 is not blade2
    assert handle1 is not handle2


def test_cached_geometry_matches_fresh_independent_computation():
    """The cache must not alter the geometry it returns: compare its
    points against a fresh call to the original (uncached) builders."""
    _ensure_qapp()
    _cached_geometry.cache_clear()

    cx, cy, size = 42.5, -13.25, 64.0

    cached_hammer, cached_blade, cached_handle = _cached_geometry(cx, cy, size)

    fresh_hammer = _hammer_polygon(cx, cy, size)
    fresh_blade = _crescent_blade_path(cx, cy, size)
    fresh_handle = _sickle_handle_polygon(cx, cy, size)

    assert list(cached_hammer) == list(fresh_hammer)
    assert list(cached_handle) == list(fresh_handle)

    assert cached_blade.elementCount() == fresh_blade.elementCount()
    for i in range(cached_blade.elementCount()):
        cached_el = cached_blade.elementAt(i)
        fresh_el = fresh_blade.elementAt(i)
        assert cached_el.x == fresh_el.x
        assert cached_el.y == fresh_el.y
        assert cached_el.type == fresh_el.type
