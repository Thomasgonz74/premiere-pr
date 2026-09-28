"""The optional theme tokens documented in style.css ("Optional theme
tokens"): unset they give the stock colours, set by a theme they repaint the
badges, the name-column glyphs and the canvases (identicons, progress mosaic)
-- the canvases through the t2k-themechange event of a mode switch."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from theme_probe import BRIDGE_STUB_JS, INJECT_JS, NO_MOTION_JS, run_js, wait_until

INDEX_HTML = Path(__file__).resolve().parents[1] / "resources" / "web" / "spike" / "index.html"

MASK = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3Crect width='1' height='1'/%3E%3C/svg%3E\")"
THEME_CSS = f""":root {{
  --risk-safe-bg: #102030; --risk-safe-text: #F0E0D0;
  --identicon-paper: #FFFFFF; --identicon-ink: #000000;
  --tetris-border: #FF0000;
  --glyph-pin: {MASK};
}}"""

# Canvas pixels cannot be read back reliably here (the offscreen GPU context
# gets lost and clears them), so the canvases are checked through the colours
# their repaint fills with: a mode switch fires t2k-themechange synchronously.
RECORD_FILLS_JS = r"""
(function () {
  window.__t2kFills = new Map();
  const fillRect = CanvasRenderingContext2D.prototype.fillRect;
  CanvasRenderingContext2D.prototype.fillRect = function (...args) {
    if (!window.__t2kFills.has(this.canvas)) window.__t2kFills.set(this.canvas, new Set());
    window.__t2kFills.get(this.canvas).add(this.fillStyle);
    return fillRect.apply(this, args);
  };
  return true;
})()
"""

# Switches mode (repaint), then reports badge colours, the pin glyph, and the
# colours the first identicon and the first mosaic were repainted with.
STATE_JS = r"""
(function () {
  window.__t2kFills.clear();
  setAppearanceMode('light');
  const fills = (el) => [...(window.__t2kFills.get(el) || [])].sort();
  const probe = document.createElement('canvas').getContext('2d');
  const hex = (css) => { probe.fillStyle = css; return probe.fillStyle; };
  const ident = document.querySelector('canvas.identicon');
  const hue = identiconHash(ident._identiconHash) % 360;
  const pin = getComputedStyle(document.querySelector('.row-glyph-pin'), '::before');
  const good = document.createElement('span'); good.className = 'reputation-badge reputation-good'; document.body.appendChild(good);
  const out = {
    stockIdenticon: [hex(`hsl(${hue}, 60%, 92%)`), hex(`hsl(${hue}, 65%, 42%)`)].sort(),
    identicon: fills(ident),
    mosaic: fills(document.querySelector('canvas.tetris')),
    pinContent: pin.content, pinMask: pin.maskImage.slice(0, 4),
    riskSafe: getComputedStyle(document.querySelector('.risk-safe')).backgroundColor,
    reputationGood: getComputedStyle(good).color,
  };
  good.remove();
  return JSON.stringify(out);
})()
"""


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def test_optional_tokens_default_to_the_stock_look_and_repaint_on_switch():
    view = QWebEngineView()
    view.resize(980, 640)
    view.setUrl(QUrl.fromLocalFile(str(INDEX_HTML)))
    view.show()
    try:
        wait_until(view, "document.readyState === 'complete' && typeof downloadsRenderRecord === 'function'")
        run_js(view, NO_MOTION_JS)
        run_js(view, BRIDGE_STUB_JS)
        run_js(view, INJECT_JS)
        run_js(view, RECORD_FILLS_JS)

        stock = json.loads(run_js(view, STATE_JS))
        assert stock["identicon"] and set(stock["identicon"]) <= set(stock["stockIdenticon"])
        assert "#0f380f" in stock["mosaic"]  # grid, Game Boy darkest
        assert set(stock["mosaic"]) <= {"#0f380f", "#306230", "#8bac0f", "#9bbc0f"}
        assert (stock["pinContent"], stock["pinMask"]) == ('"\U0001F4CC"', "none")
        assert (stock["riskSafe"], stock["reputationGood"]) == ("rgb(223, 243, 223)", "rgb(31, 122, 31)")

        run_js(view, f"const s = document.createElement('style'); s.id = 't2k-test-tokens'; s.textContent = {json.dumps(THEME_CSS)}; document.head.appendChild(s); true")
        themed = json.loads(run_js(view, STATE_JS))
        assert "#ffffff" in themed["identicon"] and set(themed["identicon"]) <= {"#000000", "#ffffff"}
        assert "#ff0000" in themed["mosaic"] and "#0f380f" not in themed["mosaic"]
        assert (themed["pinContent"], themed["pinMask"]) == ('"" / "\U0001F4CC"', "url(")
        assert (themed["riskSafe"], themed["reputationGood"]) == ("rgb(16, 32, 48)", "rgb(240, 224, 208)")

        run_js(view, "document.getElementById('t2k-test-tokens').remove(); true")
        restored = json.loads(run_js(view, STATE_JS))
        assert "#0f380f" in restored.pop("mosaic")  # the pieces keep falling: only the grid is fixed
        stock.pop("mosaic")
        assert restored == stock
    finally:
        view.close()
        view.deleteLater()
        waited = 0
        while shiboken6.isValid(view) and waited < 10_000:
            QTest.qWait(50)
            waited += 50
