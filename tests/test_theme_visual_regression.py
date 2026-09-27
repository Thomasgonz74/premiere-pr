"""Visual regression test for the 34 web-UI CSS themes under
resources/web/spike/themes/.

Loads the real resources/web/spike/index.html once in an offscreen
QWebEngineView (same QT_QPA_PLATFORM=offscreen convention as the rest of the
test suite -- see tests/test_theme_cursor.py etc.), then for each theme calls
the app's own setActiveTheme() JS (theme_switcher.js swaps the
#themeTokensLink <link> href live, no reload -- see spike_window.py /
theme_switcher.js), grabs a full-window screenshot in each appearance mode,
and compares it to a reference PNG stored at
tests/fixtures/theme_snapshots/<theme_id>[__dark|__dark_hc].png.

The diff is a generous, sampled mean per-channel color difference -- not a
strict pixel-for-pixel diff -- because antialiasing/sub-pixel rendering
varies slightly machine to machine; this only needs to catch real breakage
(wrong colors, missing CSS, broken layout), not GPU/font-hinting noise.

First run for a theme (no reference PNG yet): the render is saved as the new
reference and the test PASSES, with a clear log line -- rerun once to
actually verify against it, same "create-then-verify" shape as any other
snapshot-testing setup.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform gives the QQuickWidget inside QWebEngineView no RHI
# surface, so grab() only ever returned the widget's own background: every
# reference PNG was a blank white 980x640 and the test compared nothing. The
# software scene graph renders Chromium's frames into the widget, so grab()
# sees the real page. Set at import (collection runs before any test creates
# the first Qt Quick scene).
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from theme_probe import NO_MOTION_JS, run_js, set_mode, set_theme

REPO_ROOT = Path(__file__).resolve().parents[1]
THEMES_DIR = REPO_ROOT / "resources" / "web" / "spike" / "themes"
INDEX_HTML = REPO_ROOT / "resources" / "web" / "spike" / "index.html"
SNAPSHOTS_DIR = REPO_ROOT / "tests" / "fixtures" / "theme_snapshots"

VIEW_SIZE = (980, 640)  # matches SpikeWindow's default resize()

# Grabbing right after setActiveTheme() races the async <link> swap, and
# grabbing mid-transition reads in-between colours: set_theme()/set_mode()
# (theme_probe.py) wait for the sheet's load event and two painted frames,
# and CSS transitions/animations are switched off for the test page.
LOAD_TIMEOUT_MS = 10_000

# Generous on purpose (2-3% suggested by the task) -- catches a theme that's
# visibly broken (wrong palette, missing structural CSS, blank page), not
# machine-level antialiasing/sub-pixel differences.
MAX_MEAN_DIFF_FRACTION = 0.03

# Fixed-size sample grid rather than scanning every pixel: keeps the diff
# cheap and bounded regardless of view resolution, with no numpy/Pillow
# dependency (neither is in pyproject.toml) -- 32x32 = 1024 sample points is
# plenty to catch a genuinely different render at this tolerance.
SAMPLE_GRID = 32


def _theme_ids() -> list[str]:
    return sorted(p.name for p in THEMES_DIR.iterdir() if (p / "tokens.css").is_file())


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def view(app):
    v = QWebEngineView()
    v.resize(*VIEW_SIZE)

    state = {"done": False, "ok": False}

    def _on_loaded(ok: bool) -> None:
        state["done"] = True
        state["ok"] = ok

    v.page().loadFinished.connect(_on_loaded)
    v.setUrl(QUrl.fromLocalFile(str(INDEX_HTML)))
    v.show()

    waited = 0
    step = 50
    while not state["done"] and waited < LOAD_TIMEOUT_MS:
        QTest.qWait(step)
        waited += step
    assert state["done"] and state["ok"], (
        f"index.html failed to load in the offscreen QWebEngineView within {LOAD_TIMEOUT_MS}ms"
    )
    assert run_js(v, NO_MOTION_JS) == "ok"

    yield v

    # QWebEngineView owns a Chromium subprocess; deleteLater() only *schedules*
    # destruction on the next event-loop pass. If it never actually runs before
    # the interpreter starts tearing down objects at process exit, the native
    # Chromium/Qt WebEngine cleanup races the shutdown and segfaults (only
    # reproduces with the full suite loaded -- see repo notes). Pump the event
    # loop until shiboken confirms the C++ object is actually gone.
    v.close()
    v.deleteLater()
    waited = 0
    while shiboken6.isValid(v) and waited < LOAD_TIMEOUT_MS:
        QTest.qWait(50)
        waited += 50


def _sample_coords(length: int, grid: int) -> list[int]:
    return sorted({min(length - 1, int((i + 0.5) * length / grid)) for i in range(grid)})


def _mean_diff_fraction(img_a: QImage, img_b: QImage) -> float:
    """Sampled mean per-channel absolute color difference, 0.0..1.0."""
    if img_a.size() != img_b.size():
        # A real regression (e.g. broken layout collapsing the page) should
        # fail loudly with a clear size mismatch, not silently short-sample.
        return 1.0
    xs = _sample_coords(img_a.width(), SAMPLE_GRID)
    ys = _sample_coords(img_a.height(), SAMPLE_GRID)
    total = 0
    count = 0
    for y in ys:
        for x in xs:
            ca, cb = img_a.pixelColor(x, y), img_b.pixelColor(x, y)
            total += abs(ca.red() - cb.red()) + abs(ca.green() - cb.green()) + abs(ca.blue() - cb.blue())
            count += 3
    return (total / count) / 255.0 if count else 0.0


# Dark and high-contrast modes are where most theme defects hid (swallowed
# dark blocks, light-on-light fields), so each theme is checked in all three.
# Light keeps its historical reference name.
MODES = (("light", ""), ("dark", "__dark"), ("dark_hc", "__dark_hc"))
# set_mode() waits for two animation frames, but the frame still has to reach
# the widget that grab() reads, and a heavy one (macos_modern's backdrop blur)
# can arrive 200 ms later: a grab taken too soon shows the previous mode, and
# macos_modern__dark.png was once saved from such a stale frame. So after the
# switch a 1 px marker at (0, 0) -- never sampled by _mean_diff_fraction --
# takes a new colour, and grab() is repeated until it shows that colour: the
# frame is then at least as new as the mode switch.
MARKER_JS = r"""
(function () {
  let m = document.getElementById('t2k-test-frame-marker');
  if (!m) {
    m = document.createElement('div');
    m.id = 't2k-test-frame-marker';
    m.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;z-index:2147483647;pointer-events:none';
    document.documentElement.appendChild(m);
  }
  const n = (Number(m.dataset.n) || 0) % 200 + 1;
  m.dataset.n = n;
  m.style.background = `rgb(${n}, 64, 192)`;
  return n;
})()
"""
FRESH_FRAME_TIMEOUT_MS = 5_000


def _grab_fresh(view: QWebEngineView) -> QImage:
    marker = (int(run_js(view, MARKER_JS)), 64, 192)
    waited = 0
    while True:
        image = view.grab().toImage().convertToFormat(QImage.Format_RGB888)
        assert not image.isNull(), "grab() produced an empty image"
        c = image.pixelColor(0, 0)
        if (c.red(), c.green(), c.blue()) == marker:
            return image
        assert waited < FRESH_FRAME_TIMEOUT_MS, f"no grab showed the frame marker within {FRESH_FRAME_TIMEOUT_MS} ms"
        QTest.qWait(20)
        waited += 20


@pytest.mark.parametrize("theme_id", _theme_ids())
def test_theme_visual_regression(view: QWebEngineView, theme_id: str) -> None:
    set_theme(view, theme_id)
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    problems = []
    try:
        for mode, suffix in MODES:
            set_mode(view, mode)
            rendered = _grab_fresh(view)
            ref_path = SNAPSHOTS_DIR / f"{theme_id}{suffix}.png"
            if not ref_path.is_file():
                assert rendered.save(str(ref_path), "PNG"), f"failed to write new reference {ref_path}"
                print(
                    f"\n[test_theme_visual_regression] No reference snapshot existed for "
                    f"theme '{theme_id}' ({mode}) -- created {ref_path}. Re-run the test suite once "
                    "to actually verify future renders against it."
                )
                continue
            reference = QImage(str(ref_path)).convertToFormat(QImage.Format_RGB888)
            assert not reference.isNull(), f"reference image {ref_path} exists but failed to load"
            diff = _mean_diff_fraction(rendered, reference)
            if diff > MAX_MEAN_DIFF_FRACTION:
                problems.append(
                    f"{mode}: {diff:.4f} mean per-channel diff exceeds tolerance {MAX_MEAN_DIFF_FRACTION} "
                    f"against {ref_path} (delete the reference to intentionally re-baseline)"
                )
    finally:
        set_mode(view, "light")
    assert not problems, f"theme '{theme_id}': visual regression detected --\n  " + "\n  ".join(problems)


def test_theme_dirs_found():
    # Sanity check the enumeration itself isn't silently empty/short --
    # mirrors test_theme_hc_contrast.py's own guard.
    assert len(_theme_ids()) == 34
