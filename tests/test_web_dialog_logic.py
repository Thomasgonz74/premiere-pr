"""Behaviour of a few web-UI scripts that run without any bridge round trip
(modal.js, profile_stats.js, piece_map_dialog.js), exercised in the real
resources/web/spike/index.html loaded in an offscreen QWebEngineView with
hand-made bridge stubs (same page-loading convention as
test_theme_readability.py)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from theme_probe import TIMEOUT_MS, run_js, wait_until

INDEX_HTML = Path(__file__).resolve().parents[1] / "resources" / "web" / "spike" / "index.html"


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
    yield v
    # Same teardown as test_theme_visual_regression: let Chromium's C++ side
    # go away before interpreter shutdown, or the process can crash at exit.
    v.close()
    v.deleteLater()
    waited = 0
    while shiboken6.isValid(v) and waited < TIMEOUT_MS:
        QTest.qWait(50)
        waited += 50


def test_opening_a_modal_closes_the_one_it_replaces(view):
    result = run_js(view, """(function () {
      window.bridge = { autoShutdown: { cancelShutdown() {} } };
      let pollStopped = 0;
      openModal('poll', document.createElement('div'), () => { pollStopped++; });
      openModal('other', document.createElement('div'));
      // A second countdown pushed while the first is open must keep ticking:
      // opening it runs the first one's onClose.
      showAutoShutdownCountdown(30, 'shutdown');
      showAutoShutdownCountdown(30, 'shutdown');
      const ticking = _shutdownCountdownTimer !== null;
      closeModal();
      return JSON.stringify([pollStopped, ticking, _shutdownCountdownTimer]);
    })()""")
    assert result == "[1,true,null]"


def test_history_refresh_is_coalesced_and_skipped_while_profile_is_hidden(view):
    run_js(view, """
      window.__historyFetches = 0;
      window.bridge = {
        dialogs: {},
        profileStats: {
          getStatsSnapshot() {},
          snapshotUpdated: { connect() {} },
          getHistoryEntries(cb) { window.__historyFetches++; cb([]); },
          historyChanged: { connect(fn) { window.__historyChanged = fn; } },
        },
      };
      switchToTab('downloads');
      wireProfileStats();
      true""")
    assert run_js(view, "window.__historyFetches") == 1  # initial load

    run_js(view, "for (let i = 0; i < 20; i++) window.__historyChanged(); true")
    QTest.qWait(300)
    assert run_js(view, "window.__historyFetches") == 1  # hidden: nothing fetched

    run_js(view, "switchToTab('profile'); true")
    assert run_js(view, "window.__historyFetches") == 2  # opening the page refreshes at once

    run_js(view, "for (let i = 0; i < 20; i++) window.__historyChanged(); true")
    wait_until(view, "window.__historyFetches === 3")
    QTest.qWait(300)
    assert run_js(view, "window.__historyFetches") == 3  # 20 signals, one fetch


def test_piece_map_decodes_the_bridge_strings(view):
    result = run_js(view, """(function () {
      const fills = [];
      const ctx = { set fillStyle(v) { this.c = v; }, fillRect() { fills.push(this.c); } };
      _drawPieceMap(ctx, null, 2, { numPieces: 4, have: '1000', availability: '0023' }, null);
      const expected = [PIECE_MAP_COLOR_HAVE, PIECE_MAP_COLOR_MISSING_NONE,
                        PIECE_MAP_COLOR_MISSING_RARE, PIECE_MAP_COLOR_MISSING_COMMON];
      return fills.join() === expected.join() ? 'ok' : fills.join();
    })()""")
    # A "0" have char is truthy in JS: decoded wrong, every cell turns green.
    assert result == "ok"
