"""Behaviour of a few web-UI scripts that run without any bridge round trip
(modal.js, profile_stats.js, piece_map_dialog.js, downloads.js,
theme_switcher.js, profile_general.js), exercised in
the real resources/web/spike/index.html loaded in an offscreen QWebEngineView
with hand-made bridge stubs (same page-loading convention as
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
      const replaced = [];
      openModal('poll', document.createElement('div'), (info) => { replaced.push(info.replaced); });
      openModal('other', document.createElement('div'), (info) => { replaced.push(info.replaced); });
      // A second countdown pushed while the first is open must keep ticking:
      // opening it runs the first one's onClose.
      showAutoShutdownCountdown(30, 'shutdown');
      showAutoShutdownCountdown(30, 'shutdown');
      const ticking = _shutdownCountdownTimer !== null;
      closeModal();
      return JSON.stringify([replaced, ticking, _shutdownCountdownTimer]);
    })()""")
    # onClose learns whether it was replaced (the first-launch welcome is
    # only marked seen on a real close) or closed.
    assert result == "[[true,true],true,null]"


def test_share_banner_only_announces_limits_reached_this_session(view):
    result = run_js(view, """(function () {
      const sig = () => { const cbs = []; return { connect: (f) => cbs.push(f), emit: (...a) => cbs.forEach((f) => f(...a)) }; };
      const share = { recordUpdated: sig(), recordsUpdated: sig(),
                      listTorrents(cb) { cb([{ infoHash: 'old', reached: true }, { infoHash: 'fresh', reached: false }]); } };
      window.bridge = { share, profileAutomation: { lowSpaceWarning: sig() } };
      wireSuggestionBanner();
      const banner = document.getElementById('downloadsSuggestionBanner');
      const seen = [];
      // set_live(true) resync: reached in a previous session, not now.
      share.recordsUpdated.emit([{ infoHash: 'old', reached: true }, { infoHash: 'fresh', reached: false }]);
      share.recordsUpdated.emit([{ infoHash: 'late', reached: true }]);  // first sighting
      seen.push(banner.hidden);
      share.recordUpdated.emit({ infoHash: 'fresh', reached: true });  // reached now
      seen.push(banner.hidden);
      hideSuggestionBanner();
      share.recordsUpdated.emit([{ infoHash: 'fresh', reached: true }]);
      seen.push(banner.hidden);
      // The "limit reached" push is itself a change made this session, even
      // for a torrent tracked while the window was hidden (never listed).
      share.recordUpdated.emit({ infoHash: 'unseen', reached: true });
      seen.push(banner.hidden);
      return JSON.stringify(seen);
    })()""")
    assert result == "[true,false,true,false]"


def test_removing_tagged_torrents_refreshes_the_tag_filter_once(view):
    run_js(view, """
      window.__tagFetches = 0;
      window.bridge = { downloads: { listAllTags(cb) { window.__tagFetches++; cb([]); } } };
      downloadsTagsCache.set('t1', ['a']);
      downloadsTagsCache.set('t2', ['b']);
      downloadsTagsCache.set('u1', []);
      downloadsRemoveRecord('u1');
      true""")
    QTest.qWait(300)
    assert run_js(view, "window.__tagFetches") == 0  # known to have no tag: none could have gone

    run_js(view, "downloadsRemoveRecord('never-fetched'); true")  # its tags were never loaded
    wait_until(view, "window.__tagFetches === 1")

    run_js(view, "downloadsRemoveRecord('t1'); downloadsRemoveRecord('t2'); true")
    wait_until(view, "window.__tagFetches === 2")
    QTest.qWait(300)
    assert run_js(view, "window.__tagFetches") == 2  # two removals, one refresh


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


def test_dark_on_a_theme_without_one_is_applied_as_light_and_kept(view):
    result = run_js(view, """(function () {
      const attr = () => document.documentElement.getAttribute('data-theme');
      const seen = [];
      setActiveTheme('synthwave'); setAppearanceMode('dark'); seen.push(attr());
      setActiveTheme('win11_mica'); seen.push(attr());  // the saved dark comes back
      setAppearanceMode('dark_hc'); setActiveTheme('synthwave'); seen.push(attr());
      setActiveTheme('luna_xp'); setAppearanceMode('light');
      return JSON.stringify(seen);
    })()""")
    assert result == '[null,"dark","hc"]'


def test_appearance_selector_offers_dark_only_where_it_exists(view):
    result = run_js(view, """(function () {
      const sig = () => { const cbs = []; return { connect: (f) => cbs.push(f), emit: (...a) => cbs.forEach((f) => f(...a)) }; };
      const saved = [];
      const profileGeneral = {
        themeChanged: sig(),
        getSettings(cb) { cb({ theme: 'synthwave', appearanceMode: 'dark', audioVolume: 50 }); },
        getThemeOptions(cb) { cb([]); },
        getAppearanceModeOptions(cb) { cb([{ id: 'light', label: 'Clair' }, { id: 'dark', label: 'Sombre' }, { id: 'dark_hc', label: 'Contraste' }]); },
        getLanguageOptions(cb) { cb([]); },
        getLaunchAtStartupActual(cb) { cb(false); },
        setAppearanceMode(mode) { saved.push(mode); },
      };
      window.bridge = { profileGeneral, dialogs: {} };
      wireProfileGeneral();
      const select = document.getElementById('pgAppearanceSelect');
      const seen = [];
      const look = () => seen.push(Array.from(select.options, (o) => o.value).join() + ' ' + select.value);
      look();
      profileGeneral.themeChanged.emit('win11_mica', 'dark');
      look();
      profileGeneral.themeChanged.emit('tui-dos', 'dark');
      look();
      select.value = 'dark_hc';
      select.dispatchEvent(new Event('change'));
      return JSON.stringify([seen, saved]);
    })()""")
    # Showing "light" for a saved dark saves nothing; only the user's change does.
    assert result == '[["light,dark_hc light","light,dark,dark_hc dark","light,dark_hc light"],["dark_hc"]]'
