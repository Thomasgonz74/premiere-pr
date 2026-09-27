"""Opt-in resize-fluidity probe (T2K_RESIZE_PROBE=1).

For every native drag-resize gesture, measures how long Chromium takes to
paint each window size the OS delivered (resizeEvent -> first rAF frame at
that size) and appends one JSON line per gesture to
%TEMP%\\t2k_resize_probe.jsonl (also logged). time.perf_counter() and
performance.now() both run on QueryPerformanceCounter, so a single round
trip at idle aligns the two clocks.

With the resize freeze on (the default), the view is not resized during the
gesture: every step is "never rendered" by design and only
final_frame_after_release_ms is meaningful.
"""

import ctypes
import json
import logging
import statistics
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)

PROBE_PATH = Path(tempfile.gettempdir()) / "t2k_resize_probe.jsonl"

# Records every distinct (innerWidth, innerHeight) with the time of the
# animation frame that first showed it.
_RAF_JS = (
    "window.__t2kL=[];(function f(){const L=window.__t2kL,w=innerWidth,h=innerHeight,p=L[L.length-1];"
    "if(!p||p[1]!==w||p[2]!==h){if(L.length>4000)L.splice(0,2000);L.push([performance.now(),w,h]);}"
    "requestAnimationFrame(f);})();"
)


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def summarize(steps, frames, enter_t, exit_t) -> dict:
    """steps: [(t, w, h)] sizes delivered to the window; frames: [(t, w, h)]
    sizes painted by Chromium, already on the same clock (ms)."""
    lags, missed = [], 0
    for t, w, h in steps:
        hit = next((ft for ft, fw, fh in frames if (fw, fh) == (w, h) and ft >= t - 1), None)
        if hit is None:
            missed += 1
        else:
            lags.append(hit - t)
    settle = None
    if steps:
        _, w, h = steps[-1]
        last = next((ft for ft, fw, fh in frames if (fw, fh) == (w, h) and ft >= steps[-1][0] - 1), None)
        settle = None if last is None else round(last - exit_t, 1)
    gaps = [b[0] - a[0] for a, b in zip(steps, steps[1:])]
    return {
        "duration_ms": round(exit_t - enter_t),
        "resize_steps": len(steps),
        "step_rate_hz": round(len(steps) * 1000 / (exit_t - enter_t), 1) if exit_t > enter_t else None,
        "step_gap_ms_p50": round(statistics.median(gaps), 1) if gaps else None,
        "chromium_frames": sum(1 for ft, _, _ in frames if enter_t <= ft <= exit_t),
        "steps_never_rendered": missed,
        "lag_ms_p50": round(statistics.median(lags), 1) if lags else None,
        "lag_ms_p90": round(statistics.quantiles(lags, n=10)[8], 1) if len(lags) >= 10 else None,
        "lag_ms_max": round(max(lags), 1) if lags else None,
        "final_frame_after_release_ms": settle,
    }


class ResizeProbe:
    def __init__(self, window, view, freeze_enabled: bool) -> None:
        self._window = window
        self._view = view
        self._freeze = freeze_enabled
        self._offset = None  # performance.now() minus _now_ms()
        self._rtt = None
        self._enter = None
        self._steps = []
        self._grab_ms = None

    def on_page_loaded(self) -> None:
        self._view.page().runJavaScript(_RAF_JS)
        QTimer.singleShot(1500, self._calibrate)

    def _calibrate(self) -> None:
        t0 = _now_ms()

        def done(js_now):
            t1 = _now_ms()
            self._offset, self._rtt = float(js_now) - (t0 + t1) / 2, t1 - t0

        self._view.page().runJavaScript("performance.now()", 0, done)

    def on_enter(self) -> None:
        self._enter, self._steps, self._grab_ms = _now_ms(), [], None

    def on_resize(self, w: int, h: int) -> None:
        if self._enter is not None:
            self._steps.append((_now_ms(), w, h))

    def note_grab(self, ms: float) -> None:
        self._grab_ms = round(ms, 1)

    def on_exit(self) -> None:
        if self._enter is None:
            return
        gesture = (self._enter, _now_ms(), self._steps, self._grab_ms)
        self._enter = None
        # Leave Chromium time to paint the final size before draining its log.
        QTimer.singleShot(500, lambda: self._view.page().runJavaScript(
            "JSON.stringify(window.__t2kL?window.__t2kL.splice(0):[])", 0,
            lambda raw: self._report(*gesture, raw)))

    def _report(self, enter_t, exit_t, steps, grab_ms, raw) -> None:
        if self._offset is None:
            logger.warning("resize probe: clocks not aligned yet, gesture skipped")
            return
        frames = [(t - self._offset, w, h) for t, w, h in json.loads(raw or "[]")]
        handle = self._window.windowHandle()
        exstyle = ctypes.windll.user32.GetWindowLongPtrW(int(self._window.winId()), -20)
        record = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "swap_interval": handle.requestedFormat().swapInterval(),
            "surface": handle.surfaceType().name,
            "ws_ex_layered": bool(exstyle & 0x80000),
            "freeze": self._freeze,
            "freeze_grab_ms": grab_ms,
            "clock_rtt_ms": round(self._rtt, 1),
            **summarize(steps, frames, enter_t, exit_t),
        }
        try:
            with PROBE_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            logger.exception("resize probe: cannot write %s", PROBE_PATH)
        logger.info("resize probe: %s", record)
