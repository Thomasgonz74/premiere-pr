"""The optional theme tokens documented in style.css ("Optional theme
tokens"): unset they give the stock colours, set by a theme they repaint the
badges, the name-column glyphs and the canvases (identicons, progress mosaic)
-- the canvases through the t2k-themechange event of a mode switch or of a
new theme sheet's load."""
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
# Loaded through a theme switch (the sheet's onload path) instead.
SL_CSS = ":root { --identicon-paper-sl: 0% 100%; --identicon-ink-sl: 0% 0%; --tetris-border: #0000FF; }"

# The ink is checked on a canvas whose hash draws blocks ("t2k1": 12 fills).
TEST_IDENTICON_JS = r"""
(function () {
  const c = document.createElement('canvas');
  c.className = 'identicon'; c.id = 't2k-test-identicon'; c.width = c.height = 20;
  document.body.appendChild(c);
  drawIdenticon(c, 't2k1');
  return true;
})()
"""

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
  const ident = document.getElementById('t2k-test-identicon');
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


def _dispose(view):
    view.close()
    view.deleteLater()
    waited = 0
    while shiboken6.isValid(view) and waited < 10_000:
        QTest.qWait(50)
        waited += 50


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
        run_js(view, TEST_IDENTICON_JS)

        stock = json.loads(run_js(view, STATE_JS))
        assert sorted(stock["identicon"]) == stock["stockIdenticon"]  # paper and ink both painted
        assert "#0f380f" in stock["mosaic"]  # grid, Game Boy darkest
        assert set(stock["mosaic"]) <= {"#0f380f", "#306230", "#8bac0f", "#9bbc0f"}
        assert (stock["pinContent"], stock["pinMask"]) == ('"\U0001F4CC"', "none")
        assert (stock["riskSafe"], stock["reputationGood"]) == ("rgb(223, 243, 223)", "rgb(31, 122, 31)")

        run_js(view, f"const s = document.createElement('style'); s.id = 't2k-test-tokens'; s.textContent = {json.dumps(THEME_CSS)}; document.head.appendChild(s); true")
        themed = json.loads(run_js(view, STATE_JS))
        assert themed["identicon"] == ["#000000", "#ffffff"]
        assert "#ff0000" in themed["mosaic"] and "#0f380f" not in themed["mosaic"]
        assert (themed["pinContent"], themed["pinMask"]) == ('"" / "\U0001F4CC"', "url(")
        assert (themed["riskSafe"], themed["reputationGood"]) == ("rgb(16, 32, 48)", "rgb(240, 224, 208)")

        run_js(view, "document.getElementById('t2k-test-tokens').remove(); true")
        restored = json.loads(run_js(view, STATE_JS))
        assert "#0f380f" in restored.pop("mosaic")  # the pieces keep falling: only the grid is fixed
        stock.pop("mosaic")
        assert restored == stock

        # A theme switch repaints once the new sheet has loaded (link.onload).
        run_js(view, f"""(function () {{
            const s = document.createElement('style'); s.textContent = {json.dumps(SL_CSS)}; document.head.appendChild(s);
            window.__t2kThemeEvents = 0;
            document.addEventListener('t2k-themechange', () => window.__t2kThemeEvents++);
            window.__t2kFills.clear();
            setActiveTheme('win95_classic'); return true;
        }})()""")
        wait_until(view, "window.__t2kThemeEvents > 0")
        switched = json.loads(run_js(view, """JSON.stringify({
            identicon: [...window.__t2kFills.get(document.getElementById('t2k-test-identicon'))].sort(),
            mosaic: [...(window.__t2kFills.get(document.querySelector('canvas.tetris')) || [])]})"""))
        assert switched["identicon"] == ["#000000", "#ffffff"]  # hsl(h 0% 0%) / hsl(h 0% 100%)
        assert "#0000ff" in switched["mosaic"]
    finally:
        _dispose(view)


def test_identicons_draw_a_pattern_that_tells_torrents_apart():
    """With a monochrome pair the 5x5 pattern is all that tells torrents
    apart: nearly every hash must draw blocks, and different hashes different
    patterns (the LCG used to overflow 2^53 and draw none for ~97 % of them)."""
    view = QWebEngineView()
    view.resize(980, 640)
    loaded = {}
    view.page().loadFinished.connect(lambda ok: loaded.setdefault("ok", ok))
    view.setUrl(QUrl.fromLocalFile(str(INDEX_HTML)))
    view.show()
    try:
        waited = 0
        while "ok" not in loaded and waited < 10_000:
            QTest.qWait(50)
            waited += 50
        assert loaded.get("ok"), "index.html failed to load"
        result = run_js(view, r"""(function () {
          const patterns = new Set();
          let withBlocks = 0;
          for (let i = 1; i <= 200; i++) {
            const c = document.createElement('canvas');
            c.width = c.height = 20;
            const ctx = c.getContext('2d');
            const rects = [];
            const fill = ctx.fillRect.bind(ctx);
            ctx.fillRect = (...a) => { rects.push(a.join(',')); fill(...a); };
            drawIdenticon(c, (Math.imul(i, 2654435761) >>> 0).toString(16).padStart(8, '0').repeat(5));
            if (rects.length > 1) withBlocks++;  // the first fill is the background
            patterns.add(rects.slice(1).join(';'));
          }
          return JSON.stringify([withBlocks, patterns.size]);
        })()""")
        with_blocks, distinct = json.loads(result)
        assert with_blocks >= 190, f"only {with_blocks}/200 identicons draw a block"
        assert distinct >= 150, f"only {distinct} distinct patterns for 200 hashes"
    finally:
        _dispose(view)


# The four data dialogs, fed fixed bridge answers. A dialog stays open while a
# mode switch fires t2k-themechange: it must repaint at once, the piece map
# every cell although its snapshot has not changed.
DATA_DIALOGS_JS = r"""
(function () {
  const base = window.bridge;
  const snapshot = {numPieces: 4, have: '1000', availability: '0023'};
  const files = [{path: 'a/x', size: 3, downloaded: 3}, {path: 'a/y', size: 3, downloaded: 1}, {path: 'b/z', size: 3, downloaded: 0}];
  const stubs = {
    speedGraph: {getSpeedHistory: (h, cb) => cb([[5, 1], [2, 4], [7, 3]])},
    pieceMap: {getPieceAvailability: (h, cb) => cb(snapshot)},
    swarmConstellation: {getPeers: (h, cb) => cb([1, 0.6, 0.2, 0].map((progress) => ({progress})))},
    storageSunburst: {getFileBreakdown: (h, cb) => cb(files.map((f) => ({...f}))), getFileProgress: (h, cb) => cb(files.map((f) => f.downloaded))},
  };
  window.bridge = new Proxy({}, {get: (_, k) => stubs[k] || base[k]});
  window.__t2kPaints = new Map();  // canvas -> styles; the dialog paints before it is attached
  const P = CanvasRenderingContext2D.prototype;
  for (const [op, style] of [['fill', 'fillStyle'], ['fillRect', 'fillStyle'], ['fillText', 'fillStyle'], ['stroke', 'strokeStyle']]) {
    const orig = P[op];
    P[op] = function (...a) {
      if (!window.__t2kPaints.has(this.canvas)) window.__t2kPaints.set(this.canvas, new Set());
      window.__t2kPaints.get(this.canvas).add(this[style]);
      return orig.apply(this, a);
    };
  }
  window.__t2kDialogPaints = (repaint) => {
    if (repaint) { window.__t2kPaints.clear(); setAppearanceMode('light'); }  // fires t2k-themechange
    const legend = [...document.querySelectorAll('#modalBox div[style*="width: 10px"]')].map((el) => getComputedStyle(el).backgroundColor);
    const canvas = [...(window.__t2kPaints.get(document.querySelector('#modalBox canvas')) || [])].sort();
    return JSON.stringify({canvas, legend});
  };
  return true;
})()
"""
DATA_TOKENS_CSS = """:root { --piece-have: #000000; --piece-common: #333333; --piece-rare: #666666; --piece-none: #ffffff;
  --speed-up: #999999; --speed-grid: #aaaaaa; --speed-axis: #bbbbbb;
  --swarm-ring: #cccccc; --swarm-orbit: #dddddd; --swarm-link: #eeeeee; --sunburst-stroke: #111111; }"""
G, B, O, R = "#4caf50", "#5b7c99", "#e67e22", "#c0392b"
RGB = {G: "rgb(76, 175, 80)", B: "rgb(91, 124, 153)", O: "rgb(230, 126, 34)", R: "rgb(192, 57, 43)",
       "#000000": "rgb(0, 0, 0)", "#333333": "rgb(51, 51, 51)", "#666666": "rgb(102, 102, 102)", "#ffffff": "rgb(255, 255, 255)", "#999999": "rgb(153, 153, 153)"}
# dialog: (stock canvas paints, stock legend, themed canvas paints, themed legend)
DATA_DIALOGS = {
    "openPieceMapDialog": ({G, B, O, R}, [G, B, O, R], {"#000000", "#333333", "#666666", "#ffffff"}, ["#000000", "#333333", "#666666", "#ffffff"]),
    "openSpeedGraphDialog": ({G, O, "#808080", "rgba(128, 128, 128, 0.24)"}, [G, O],
                             {"#000000", "#999999", "#aaaaaa", "#bbbbbb"}, ["#000000", "#999999"]),
    "openSwarmConstellationDialog": ({G, B, O, R, "#ffffff", "rgba(128, 128, 128, 0.15)", "rgba(128, 128, 128, 0.2)"}, [G, G, B, O, R],
                                     {"#000000", "#333333", "#666666", "#ffffff", "#cccccc", "#dddddd", "#eeeeee"},
                                     ["#000000", "#000000", "#333333", "#666666", "#ffffff"]),
    "openStorageSunburstDialog": ({G, O, R, "rgba(0, 0, 0, 0.15)"}, [G, O, R], {"#000000", "#666666", "#ffffff", "#111111"}, ["#000000", "#666666", "#ffffff"]),
}


def test_data_dialog_tokens_default_to_the_stock_colours_and_repaint_open_dialogs():
    view = QWebEngineView()
    view.resize(980, 640)
    view.setUrl(QUrl.fromLocalFile(str(INDEX_HTML)))
    view.show()
    try:
        wait_until(view, "document.readyState === 'complete' && typeof openPieceMapDialog === 'function'")
        run_js(view, BRIDGE_STUB_JS)
        run_js(view, DATA_DIALOGS_JS)
        for opener, (stock_canvas, stock_legend, themed_canvas, themed_legend) in DATA_DIALOGS.items():
            run_js(view, f"window.__t2kPaints.clear(); {opener}('h', 'n'); true")
            opened = json.loads(run_js(view, "window.__t2kDialogPaints(false)"))
            stock = json.loads(run_js(view, "window.__t2kDialogPaints(true)"))  # a repaint, still unthemed
            assert set(opened["canvas"]) == set(stock["canvas"]) == stock_canvas, opener
            assert stock["legend"] == [RGB[c] for c in stock_legend], opener

            run_js(view, f"{{ const s = document.createElement('style'); s.id = 't2k-test-data'; s.textContent = {json.dumps(DATA_TOKENS_CSS)}; document.head.appendChild(s); }} true")
            themed = json.loads(run_js(view, "window.__t2kDialogPaints(true)"))
            assert set(themed["canvas"]) == themed_canvas, opener
            assert themed["legend"] == [RGB[c] for c in themed_legend], opener
            run_js(view, "document.getElementById('t2k-test-data').remove(); closeModal(); setAppearanceMode('light'); true")
    finally:
        _dispose(view)
