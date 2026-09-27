"""Readability of the 34 web-UI themes, measured in the real page.

For every theme and every appearance mode (light / dark / high contrast), the
page is loaded with demo data (see theme_probe.py) and checked for what a user
actually reads: WCAG contrast >= 4.5:1 on the Downloads rows (plain, selected,
warning, critical), Share/RSS/Search rows, notes, status lines, the drop zone,
scan reasons, the "?" hint, modal text and tooltip; the Name column wide
enough to read; no horizontal overflow; the progress mosaic drawn at whole
pixels; the pin state visible; at least 5 scan rows and a reachable Start
button; no tiled select background.

It also catches a theme whose dark block silently stops applying (the
early-closed comment that dropped kde-plasma's and windows-8's dark mode):
when tokens.css declares a real [data-theme="dark"] palette, the resolved
window/field/text colours must differ from light mode.
"""
from __future__ import annotations

import json
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from theme_probe import (BRIDGE_STUB_JS, EXTRA_ROWS_JS, INJECT_JS, METRICS_JS, NO_MOTION_JS, failures,
                         run_js as _js, set_mode, set_theme, settle)
from torrent2000.i18n.translator import effective_catalog

REPO_ROOT = Path(__file__).resolve().parents[1]
THEMES_DIR = REPO_ROOT / "resources" / "web" / "spike" / "themes"
INDEX_HTML = REPO_ROOT / "resources" / "web" / "spike" / "index.html"
MODES = ("light", "dark", "dark_hc")
PALETTE_TOKENS = ("--surface-window", "--surface-field", "--text-primary")
REQUIRED_TOKENS = ("--text-primary", "--surface-window", "--border-control")
TIMEOUT_MS = 10_000


def _theme_ids() -> list[str]:
    return sorted(p.name for p in THEMES_DIR.iterdir() if (p / "tokens.css").is_file())


def _declares_dark_palette(theme_id: str) -> bool:
    """True when tokens.css has a [data-theme="dark"] block redefining more
    than icons (several themes that are dark by nature only swap icons)."""
    css = re.sub(r"/\*.*?\*/", "", (THEMES_DIR / theme_id / "tokens.css").read_text(encoding="utf-8"), flags=re.S)
    for sel, body in re.findall(r"([^{}]*)\{([^{}]*)\}", css):
        # the selector itself is the last line before "{" (prose swallowed by
        # a broken comment may precede it)
        last = sel.strip().splitlines()[-1].strip() if sel.strip() else ""
        if re.fullmatch(r'(:root)?\[data-theme="dark"\]', last):
            names = [n for n in re.findall(r"(--[\w-]+)\s*:", body) if not n.startswith("--icon")]
            if len(names) >= 3:
                return True
    return False


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def view(app):
    v = QWebEngineView()
    v.resize(980, 640)
    state = {"done": False, "ok": False}
    v.page().loadFinished.connect(lambda ok: state.update(done=True, ok=ok))
    v.setUrl(QUrl.fromLocalFile(str(INDEX_HTML)))
    v.show()
    waited = 0
    while not state["done"] and waited < TIMEOUT_MS:
        QTest.qWait(50)
        waited += 50
    assert state["ok"], "index.html failed to load"
    # The app hands the catalog over before wiring any page (app.js); without
    # it t() returns raw keys, longer than the real labels, and the grid
    # measurements stop meaning anything.
    _js(v, f"setCatalog({json.dumps(effective_catalog())}); try {{ applyStaticTranslations(); }} catch (e) {{}} true")
    _js(v, BRIDGE_STUB_JS + "; 'ok'")
    assert _js(v, INJECT_JS) == "ok"
    assert _js(v, EXTRA_ROWS_JS) == "ok"
    assert _js(v, NO_MOTION_JS) == "ok"
    yield v
    # Same teardown as test_theme_visual_regression: let Chromium's C++ side
    # go away before interpreter shutdown, or the process can crash at exit.
    v.close()
    v.deleteLater()
    waited = 0
    while shiboken6.isValid(v) and waited < TIMEOUT_MS:
        QTest.qWait(50)
        waited += 50


@pytest.mark.parametrize("theme_id", _theme_ids())
def test_theme_is_readable_in_every_mode(view, theme_id):
    set_theme(view, theme_id)

    problems, palettes = [], {}
    for mode in MODES:
        set_mode(view, mode)
        _js(view, "switchToTab('downloads'); true")
        settle(view)  # layout + ResizeObserver pass that fits the mosaics
        tokens = _js(view, "JSON.stringify(Object.fromEntries(%s.map(n => [n, getComputedStyle(document.documentElement).getPropertyValue(n).trim()])))"
                     % json.dumps(sorted(set(PALETTE_TOKENS + REQUIRED_TOKENS))))
        tokens = json.loads(tokens)
        palettes[mode] = tuple(tokens[t] for t in PALETTE_TOKENS)
        problems += [f"{mode}: {t} is empty" for t in REQUIRED_TOKENS if not tokens[t]]
        metrics = json.loads(_js(view, METRICS_JS))
        problems += [f"{mode}: {p}" for p in failures(metrics)]

    if _declares_dark_palette(theme_id) and palettes["dark"] == palettes["light"]:
        problems.append("tokens.css declares a dark palette but dark mode renders the light one "
                        "(a broken rule or comment is swallowing the [data-theme=\"dark\"] block)")
    assert not problems, f"{theme_id}:\n  " + "\n  ".join(problems)
