"""Behaviour of a few web-UI scripts that run without any bridge round trip
(modal.js, profile_stats.js, piece_map_dialog.js, downloads.js, keydown.js,
theme_switcher.js, profile_general.js, add.js, file_priority.js), exercised in
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

from theme_probe import TIMEOUT_MS, run_js, set_mode, set_theme, settle, wait_until

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


def test_ip_blocklist_notice_follows_the_wait(view):
    result = run_js(view, """(function () {
      const cbs = [];
      window.bridge = { downloads: {
        ipBlocklistWaitChanged: { connect: (f) => cbs.push(f) },
        isWaitingForIpBlocklist(cb) { cb(true); },  // the wait began before the page loaded
      } };
      const notice = document.getElementById('downloadsIpBlocklistNotice');
      const seen = [notice.hidden];
      wireIpBlocklistNotice();
      seen.push(notice.hidden, getComputedStyle(notice).display !== 'none');
      cbs.forEach((f) => f(false));  // filter applied, or the load ended
      seen.push(notice.hidden, getComputedStyle(notice).display);
      return JSON.stringify(seen);
    })()""")
    assert result == '[true,false,true,true,"none"]'


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
      const expected = ['--piece-have', '--piece-none', '--piece-rare', '--piece-common'].map(dataColor);
      return fills.join() === expected.join() ? 'ok' : fills.join();
    })()""")
    # A "0" have char is truthy in JS: decoded wrong, every cell turns green.
    assert result == "ok"


def _switch_theme(view, theme_id):
    """setActiveTheme(), then waits for the new sheet; returns data-theme as
    it was right after the call, while the old sheet was still painted."""
    attr = run_js(view, f"""(function () {{
      window.__t2kThemeLoaded = false;
      document.getElementById('themeTokensLink').addEventListener('load', () => {{ window.__t2kThemeLoaded = true; }}, {{once: true}});
      setActiveTheme({theme_id!r});
      return String(document.documentElement.getAttribute('data-theme'));
    }})()""")
    wait_until(view, "window.__t2kThemeLoaded === true")
    settle(view)
    return attr, run_js(view, "String(document.documentElement.getAttribute('data-theme'))")


def test_dark_on_a_theme_without_one_is_applied_as_light_and_kept(view):
    set_theme(view, "win11_mica")
    set_mode(view, "dark")
    # Leaving a dark palette: "dark" stays on until synthwave's sheet is in
    # (no flash of win11_mica light), then it shows as light.
    assert _switch_theme(view, "synthwave") == ("dark", "null")
    # The saved dark comes back, already on before win11_mica's sheet lands.
    assert _switch_theme(view, "win11_mica") == ("dark", "dark")
    assert _switch_theme(view, "tui-dos") == ("dark", "null")
    assert _switch_theme(view, "synthwave") == ("null", "null")
    set_mode(view, "dark_hc")
    assert _switch_theme(view, "art-deco") == ("hc", "hc")
    set_theme(view, "luna_xp")
    set_mode(view, "light")


def test_appearance_selector_offers_dark_only_where_it_exists(view):
    result = run_js(view, """(function () {
      const sig = () => { const cbs = []; return { connect: (f) => cbs.push(f), emit: (...a) => cbs.forEach((f) => f(...a)) }; };
      const saved = [];
      const profileGeneral = {
        themeChanged: sig(),
        languageChanged: sig(),
        getSettings(cb) { cb({ theme: 'synthwave', appearanceMode: 'dark', audioVolume: 50 }); },
        getThemeOptions(cb) { cb([]); },
        getAppearanceModeOptions(cb) { cb([{ id: 'light', label: 'Clair' }, { id: 'dark', label: 'Sombre' }, { id: 'dark_hc', label: 'Contraste' }]); },
        getLanguageOptions(cb) { cb([]); },
        getLaunchAtStartupActual(cb) { cb(false); },
        setAppearanceMode(mode) { saved.push(mode); },
      };
      window.bridge = { profileGeneral, dialogs: {}, profileAdvanced: { settingsApplied: sig() } };
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


def test_general_and_network_forms_reload_when_a_settings_profile_is_applied(view):
    result = run_js(view, """(function () {
      const sig = () => { const cbs = []; return { connect: (f) => cbs.push(f), emit: (...a) => cbs.forEach((f) => f(...a)) }; };
      const saved = { downloadRateLimitKbps: 1111, proxyEnabled: false, theme: 'luna_xp', appearanceMode: 'light', audioVolume: 50 };
      const noop = (cb) => cb([]);
      window.bridge = {
        dialogs: {},
        profileAdvanced: { settingsApplied: sig() },
        profileGeneral: { themeChanged: sig(), languageChanged: sig(), getSettings: (cb) => cb({ ...saved }),
                          getThemeOptions: noop, getAppearanceModeOptions: noop, getLanguageOptions: noop,
                          getLaunchAtStartupActual: (cb) => cb(false) },
        profileNetwork: { getSettings: (cb) => cb({ ...saved }), getSecuritySnapshot() {}, getRemoteAccessSettings() {} },
      };
      document.getElementById('profileGeneralContainer').replaceChildren();
      document.getElementById('profileNetworkContainer').replaceChildren();
      wireProfileGeneral();
      buildNetworkPrivacySection(document.getElementById('profileNetworkContainer'), window.bridge.profileNetwork);
      Object.assign(saved, { downloadRateLimitKbps: 1234, proxyEnabled: true });  // applyProfile
      window.bridge.profileAdvanced.settingsApplied.emit();
      return JSON.stringify([document.getElementById('pgDownloadLimit').value,
                             document.getElementById('pnProxyEnabled').checked]);
    })()""")
    # Stale 1111 / unticked would be saved back by the next Save, undoing the profile.
    assert result == '["1234",true]'


def test_appearance_labels_follow_a_language_change(view):
    result = run_js(view, """(function () {
      const sig = () => { const cbs = []; return { connect: (f) => cbs.push(f), emit: (...a) => cbs.forEach((f) => f(...a)) }; };
      let lang = 'en';
      const labels = { en: ['Light', 'Dark'], de: ['Hell', 'Dunkel'] };
      const profileGeneral = {
        themeChanged: sig(), languageChanged: sig(),
        getSettings(cb) { cb({ theme: 'luna_xp', appearanceMode: 'light', audioVolume: 50 }); },
        getThemeOptions(cb) { cb([]); },
        getAppearanceModeOptions(cb) { cb([{ id: 'light', label: labels[lang][0] }, { id: 'dark', label: labels[lang][1] }]); },
        getLanguageOptions(cb) { cb([]); },
        getLaunchAtStartupActual(cb) { cb(false); },
      };
      window.bridge = { profileGeneral, dialogs: {}, profileAdvanced: { settingsApplied: sig() } };
      document.getElementById('profileGeneralContainer').replaceChildren();
      wireProfileGeneral();
      lang = 'de';
      profileGeneral.languageChanged.emit('de');
      return Array.from(document.getElementById('pgAppearanceSelect').options, (o) => o.textContent).join();
    })()""")
    assert result == "Hell,Dunkel"


def test_network_help_hints_survive_a_language_switch(view):
    result = run_js(view, """(function () {
      const sig = () => { const cbs = []; return { connect: (f) => cbs.push(f), emit: (...a) => cbs.forEach((f) => f(...a)) }; };
      window.bridge = { profileAdvanced: { settingsApplied: sig() } };
      const container = document.getElementById('profileNetworkContainer');
      container.replaceChildren();
      buildNetworkPrivacySection(container, { getSettings() {} });
      const key = 'web.profile_network.encryption_mode_tooltip';
      setCatalog({ [key]: 'Protocol encryption help', 'web.profile_network.encryption_mode_label': 'Protocol encryption' });
      const hints = container.querySelectorAll('.info-hint');
      const label = Array.from(container.querySelectorAll('label')).find((l) => l.textContent.startsWith('Protocol encryption'));
      const seen = [hints.length, label.querySelector('.info-hint').getAttribute('data-tooltip')];
      setCatalog({});
      return JSON.stringify(seen);
    })()""")
    assert result == '[3,"Protocol encryption help"]'


def test_propaganda_messages_are_translated_once_the_catalog_arrives(view):
    result = run_js(view, """(function () {
      startPropagandaPanel();  // app.js can start it before getCatalog answers
      const catalog = {};
      for (let i = 1; i <= 18; i++) catalog['web.propaganda_panel.message_' + String(i).padStart(2, '0')] = 'Camarade ' + i;
      setCatalog(catalog);
      const first = document.getElementById('propagandaMessage').textContent;
      _showNextPropagandaMessage();
      const next = document.getElementById('propagandaMessage').textContent;
      stopPropagandaPanel();
      setCatalog({});
      return JSON.stringify([first.startsWith('Camarade '), next.startsWith('Camarade ')]);
    })()""")
    assert result == "[true,true]"


def test_removing_the_filtered_tag_hides_the_row_at_once(view):
    result = run_js(view, """(function () {
      window.bridge = { downloads: {
        getTags(ih, cb) { cb(['x']); },
        removeTag() {},
        listAllTags(cb) { cb(['x']); },  // another torrent still carries it
      } };
      const el = document.createElement('div');
      downloadsRows.set('alpha', { el, record: { infoHash: 'alpha', name: 'alpha' } });
      downloadsTagsCache.set('alpha', ['x']);
      downloadsRefreshTagFilterOptions();
      const select = document.getElementById('downloadsTagFilterSelect');
      select.value = 'x';
      downloadsTagFilterValue = 'x';
      downloadsApplyFilter();
      const seen = [el.style.display];
      // A paused torrent gets no status tick to re-filter its row later.
      downloadsOpenTagsDialog('alpha', 'alpha');
      document.querySelector('#modalBox .listbox .row button').click();
      seen.push(el.style.display);
      closeModal();
      downloadsRows.delete('alpha');
      downloadsTagsCache.delete('alpha');
      select.value = '';
      downloadsTagFilterValue = '';
      return JSON.stringify(seen);
    })()""")
    assert result == '["","none"]'


def test_a_held_magnet_row_offers_to_start_it(view):
    """AWAITING_ANALYSIS (a held magnet, not paused): ▶, the shortcut and the
    menu start it (DownloadsBridge.resumeTorrent scans it first); the menu
    still offers to pause it too."""
    result = run_js(view, """(function () {
      const calls = [];
      window.bridge = { downloads: {
        resumeTorrent(ih) { calls.push('resume'); },
        pauseTorrent(ih) { calls.push('pause'); },
      } };
      downloadsRenderRecord({ infoHash: 'held', name: 'held', progress: 0, state: 'AWAITING_ANALYSIS',
        downloadRate: 0, uploadRate: 0, numPeers: 0, numSeeds: 0, totalSize: 0, category: '' });
      const entry = downloadsRows.get('held');
      const label = entry.pauseResumeBtn.textContent;
      entry.pauseResumeBtn.click();
      const page = document.getElementById('page-downloads');
      const wasActive = page.classList.contains('active');
      page.classList.add('active');
      entry.el.classList.add('selected');
      shortcutPauseResumeSelectedDownload();
      page.classList.toggle('active', wasActive);
      const menu = downloadsBuildSingleMenu('held').map((item) => item.label);
      downloadsRemoveRecord('held');
      return JSON.stringify([label, calls, menu.includes(t('common.resume')), menu.includes(t('common.pause'))]);
    })()""")
    assert result == '["▶",["resume","resume"],true,true]'


def test_add_page_routing_destination_never_carries_over_to_the_next_torrent(view):
    result = run_js(view, """(function () {
      window.bridge = { add: { defaultDestination(cb) { cb('C:/dl'); } } };
      const dest = document.getElementById('addDestInput');
      const scan = (suggested) => addRenderScan({ fileRisks: [], threshold: 60, suggestedDestination: suggested });
      addDefaultDestination = 'C:/dl';
      dest.value = 'C:/dl';
      const seen = [];
      scan('C:/films');  // a routing rule matched
      seen.push(dest.value);
      scan('C:/dl');  // another file picked, no rule matches it
      seen.push(dest.value);
      scan('C:/films');
      addResetForm();  // started
      seen.push(dest.value);
      dest.value = 'D:/mine';
      scan('C:/films');  // typed by the user: kept
      seen.push(dest.value);
      addResetForm();
      return JSON.stringify(seen);
    })()""")
    assert result == '["C:/films","C:/dl","C:/dl","D:/mine"]'


def test_add_page_follows_a_default_folder_changed_in_profile(view):
    result = run_js(view, """(function () {
      let profileDefault = 'C:/dl';
      window.bridge = { add: { defaultDestination(cb) { cb(profileDefault); } } };
      const dest = document.getElementById('addDestInput');
      addDefaultDestination = '';
      dest.value = '';
      addRefreshDefaultDestination();  // page load
      const seen = [dest.value];
      profileDefault = 'C:/new';  // Profile > Enregistrer
      addResetForm();  // a torrent was started
      seen.push(dest.value);
      profileDefault = 'C:/newer';
      addRefreshDefaultDestination();  // the Add tab shown again
      seen.push(dest.value);
      dest.value = 'D:/mine';
      profileDefault = 'C:/newest';
      addRefreshDefaultDestination();  // typed by the user: kept
      seen.push(dest.value);
      addResetForm();
      return JSON.stringify(seen);
    })()""")
    assert result == '["C:/dl","C:/new","C:/newer","D:/mine"]'


def test_file_editor_starts_an_excluded_file_unchecked_and_saving_keeps_it_out(view):
    result = run_js(view, """(function () {
      const saved = [];
      window.bridge = { filePriority: { saveFilePriorities(ih, excluded) { saved.push(ih, excluded); } } };
      const container = document.createElement('div');
      fpRenderContent(container, 'h1', [
        { index: 0, path: 'film.mkv', size: 1, priority: 4 },
        { index: 2, path: 'film.mkv.exe', size: 1, priority: 0 },  // excluded by the danger scan
      ]);
      const checks = Array.from(container.querySelectorAll('.fp-check'), (c) => c.checked);
      container.querySelector('.modal-close-row button').click();  // Enregistrer, nothing changed
      return JSON.stringify([checks, saved]);
    })()""")
    assert result == '[[true,false],["h1",[2]]]'


def test_byte_units_follow_the_language(view):
    result = run_js(view, """(function () {
      setCatalog({ 'web.units.byte': 'B', 'web.units.kilobyte': 'KB', 'web.units.megabyte': 'MB',
                   'web.units.gigabyte': 'GB', 'web.units.per_second': '/s' });
      const seen = [formatRate(5000), formatSize(3 * 1024 * 1024), formatSize(5 * 1024 ** 3)];
      setCatalog({});
      return JSON.stringify(seen);
    })()""")
    # "4.9 Ko/s" next to "KB/s" labels in English.
    assert result == '["4.9 KB/s","3.0 MB","5.00 GB"]'


def test_a_language_switch_rebuilds_runtime_text_no_tick_would(view):
    """An idle torrent's row, the Add page's "no scan yet" note... stayed in
    the previous language until a restart."""
    result = run_js(view, """(function () {
      window.bridge = { downloads: { listAllTags(cb) { cb([]); } } };
      downloadsRenderRecord({ infoHash: 'idle', name: 'idle', progress: 1, state: 'SEEDING', downloadRate: 0,
        uploadRate: 0, numPeers: 0, numSeeds: 0, totalSize: 10, category: '', pinned: false });
      addClearScanList();
      setCatalog({ 'downloads_tab.state_seeding': 'Seeding', 'web.downloads.pin_tooltip': 'Pin to the top',
                   'web.add.no_scan_yet': 'No scan yet.' });
      const entry = downloadsRows.get('idle');
      const seen = [entry.stateEl.textContent, entry.pinBtn.title,
                    document.querySelector('#addScanList .empty-note').textContent];
      downloadsRemoveRecord('idle');
      setCatalog({});
      return JSON.stringify(seen);
    })()""")
    assert result == '["Seeding","Pin to the top","No scan yet."]'


def test_a_magnet_from_the_search_page_replaces_the_torrent_shown_and_add_fetches_once(view):
    """The previous .torrent's name and files stayed on the Add page (and
    Analyser picked it again over the magnet); a double click on a .torrent
    result fetched it twice, the second time with no title."""
    result = run_js(view, """(function () {
      if (!document.getElementById('searchResultsList')) searchBuildPage();
      const active = document.querySelector('.tab-btn.active').dataset.tab;
      const calls = [];
      window.bridge = { add: { analyzeMagnet(uri) { calls.push(['magnet', uri]); } },
                        search: { fetchTorrent(link) { calls.push(['fetch', link]); } } };
      addSelectedPath = 'C:/Temp/search_1.torrent';
      document.getElementById('addSelectedFile').textContent = 'Debian 12';
      addRenderScan({ fileRisks: [{ index: 0, path: 'debian/x.iso', size: 1, score: 0, level: 'SAFE', reasons: [] }],
                      threshold: 60, suggestedDestination: '' });
      searchRenderResults([{ title: 'some-magnet', link: 'magnet:?xt=urn:btih:abab', source: 's' },
                           { title: 'Ubuntu', link: 'http://127.0.0.1/u.torrent', source: 's' }]);
      const buttons = document.querySelectorAll('#searchResultsList .row-actions button');
      buttons[0].click();
      const shown = [addSelectedPath, document.getElementById('addSelectedFile').textContent,
                     document.querySelectorAll('#addScanList .scan-row').length];
      buttons[1].click();
      buttons[1].click();
      searchFetchTitles.clear();
      document.getElementById('searchResultsList').replaceChildren();
      switchToTab(active);
      return JSON.stringify([shown, calls]);
    })()""")
    assert result == '[[null,"",0],[["magnet","magnet:?xt=urn:btih:abab"],["fetch","http://127.0.0.1/u.torrent"]]]'


def test_german_and_russian_labels_fit_their_columns(view):
    """'↓ Geschwindigkeit' ran into the next header, 'Bearbeiten' and
    'Изменить' overflowed their buttons onto each other."""
    import json

    catalogs = {
        lang: json.loads((INDEX_HTML.parents[2] / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        for lang in ("de", "ru")
    }
    result = run_js(view, """(function (catalogs) {
      const overflow = [];
      const active = document.querySelector('.tab-btn.active').dataset.tab;
      for (const [lang, catalog] of Object.entries(catalogs)) {
        setCatalog(catalog);
        switchToTab('downloads');
        document.querySelectorAll('.downloads-row-header > span').forEach((cell) => {
          const text = document.createRange();
          text.selectNodeContents(cell);
          if (text.getBoundingClientRect().width > cell.getBoundingClientRect().width + 0.5) {
            overflow.push(lang + ' ' + cell.textContent);
          }
        });
        switchToTab('profile');
        const box = document.createElement('div');
        box.style.width = '900px';
        document.getElementById('page-profile').appendChild(box);
        arRules = [{ name: 'r', pattern: 'p', matchField: 'name', destination: 'D:/x', postCompleteAction: 'none' }];
        box.appendChild(arRuleRow(arRules[0], 0));
        box.querySelectorAll('button').forEach((b) => {
          if (b.scrollWidth > b.clientWidth) overflow.push(lang + ' ' + b.textContent);
        });
        box.remove();
      }
      arRules = [];
      setCatalog({});
      switchToTab(active);
      return JSON.stringify(overflow);
    })(""" + json.dumps(catalogs) + ")")
    assert result == "[]"


def test_a_magnet_or_torrent_opened_from_windows_replaces_the_torrent_shown(view):
    """A browser magnet link (or a second launch) went to the bridge directly:
    the previous .torrent stayed on the Add page, and Analyser picked it again."""
    import json
    from types import SimpleNamespace

    from torrent2000.ui.web.spike_window import SpikeWindow

    scripts = []
    window = SimpleNamespace(_view=SimpleNamespace(page=lambda: SimpleNamespace(runJavaScript=scripts.append)))
    SpikeWindow._run_open_source(window, "magnet:?xt=urn:btih:cdcd")
    SpikeWindow._run_open_source(window, r"C:\Users\me\Downloads\new.torrent")
    result = run_js(view, """(function (scripts) {
      const active = document.querySelector('.tab-btn.active').dataset.tab;
      const calls = [];
      window.bridge = { add: { analyzeMagnet(uri) { calls.push(['magnet', uri]); },
                               selectTorrentFile(path) { calls.push(['file', path]); } } };
      const shown = () => [addSelectedPath, document.getElementById('addSelectedFile').textContent,
                           document.querySelectorAll('#addScanList .scan-row').length];
      addSelectedPath = 'C:/Temp/old.torrent';
      document.getElementById('addSelectedFile').textContent = 'old.torrent';
      addRenderScan({ fileRisks: [{ index: 0, path: 'old/x.iso', size: 1, score: 0, level: 'SAFE', reasons: [] }],
                      threshold: 60, suggestedDestination: '' });
      (0, eval)(scripts[0]);
      const afterMagnet = shown();
      (0, eval)(scripts[1]);
      const afterFile = shown();
      addSelectedPath = null;
      document.getElementById('addSelectedFile').textContent = '';
      document.getElementById('addMagnetInput').value = '';
      addClearScanList();
      switchToTab(active);
      return JSON.stringify([afterMagnet, afterFile, calls]);
    })(""" + json.dumps(scripts) + ")")
    assert json.loads(result) == [
        [None, "", 0],
        [r"C:\Users\me\Downloads\new.torrent", "new.torrent", 0],
        [["magnet", "magnet:?xt=urn:btih:cdcd"], ["file", r"C:\Users\me\Downloads\new.torrent"]],
    ]


def test_a_magnet_from_elsewhere_drops_the_previous_torrents_routed_folder_and_magnet(view):
    """Start before its metadata came in placed the magnet in the folder the
    previous .torrent's routing rule picked; Analyser re-ran a magnet pasted
    earlier."""
    result = run_js(view, """(function () {
      const saved = [addDefaultDestination, document.getElementById('addDestInput').value];
      window.bridge = { add: { analyzeMagnet() {} } };
      const dest = document.getElementById('addDestInput');
      const magnet = document.getElementById('addMagnetInput');
      addDefaultDestination = 'C:/Downloads';
      dest.value = 'C:/Downloads';
      magnet.value = 'magnet:?xt=urn:btih:aaaa';
      addRenderScan({ fileRisks: [], threshold: 60, suggestedDestination: 'D:/Routed' });
      const routed = dest.value;
      addAnalyzeMagnet('magnet:?xt=urn:btih:bbbb');
      const seen = [routed, dest.value, magnet.value];
      dest.value = 'E:/Mine';  // typed by the user: kept
      addAnalyzeMagnet('magnet:?xt=urn:btih:cccc');
      seen.push(dest.value);
      [addDefaultDestination, dest.value] = saved;
      magnet.value = '';
      addClearScanList();
      return JSON.stringify(seen);
    })()""")
    assert result == '["D:/Routed","C:/Downloads","magnet:?xt=urn:btih:bbbb","E:/Mine"]'


def test_a_language_switch_hides_a_slowness_result_in_the_previous_language(view):
    result = run_js(view, """(function () {
      window.bridge = {
        downloads: { listAllTags(cb) { cb([]); }, getAllocatedSize(h, cb) { cb(10); } },
        trackerEditor: { getTrackers(h, cb) { cb([]); } },
      };
      downloadsRenderRecord({ infoHash: 'slow', name: 'slow', progress: 0, state: 'DOWNLOADING', downloadRate: 0,
        uploadRate: 0, numPeers: 0, numSeeds: 0, totalSize: 10, category: '', pinned: false });
      downloadsRows.get('slow').el.classList.add('selected');
      downloadsUpdateDetailsPanel();
      downloadsRenderSlownessResult({ applicable: true, causes: [{ text: 'Aucun seed' }], note: '' });  // its button
      const box = document.getElementById('downloadsDetailsSlowness');
      const shown = box.style.display + ' ' + box.textContent;
      setCatalog({ 'downloads_tab.state_downloading': 'Downloading' });
      const afterSwitch = box.style.display + ' ' + box.textContent;
      downloadsRemoveRecord('slow');
      setCatalog({});
      downloadsUpdateDetailsPanel();
      return JSON.stringify([shown, afterSwitch]);
    })()""")
    assert result == '["block Aucun seed","none "]'


def test_the_add_pages_share_policy_note_follows_a_language_switch(view):
    result = run_js(view, """(function () {
      const note = document.getElementById('addSharePolicyNote');
      let lang = 'fr';
      const asked = [];
      window.bridge = { add: { defaultSharePolicyNote(cb) {
        asked.push(lang);
        cb(lang === 'en' ? 'Default share policy active' : 'Politique de partage par défaut active');
      } } };
      note.textContent = 'Politique de partage par défaut active';  // an intent was picked
      lang = 'en';
      setCatalog({});
      const seen = [note.textContent];
      note.textContent = '';  // none shown: nothing to ask for
      setCatalog({});
      return JSON.stringify([seen, asked]);
    })()""")
    assert result == '[["Default share policy active"],["en"]]'


def test_the_add_pages_scan_reasons_and_sizes_follow_a_language_switch(view):
    """Written at the scan, they stayed in the previous language ("4.0 Ko")
    next to translated badges; the user's ticks must stay."""
    result = run_js(view, """(function () {
      window.bridge = { add: { defaultSharePolicyNote(cb) { cb(''); },
                               scanReasons(cb) { cb({ '0': ['Executable extension (exe)'] }); } } };
      setCatalog({ 'web.units.byte': 'o', 'web.units.kilobyte': 'Ko' });
      addRenderScan({ threshold: 50, fileRisks: [
        { index: 0, path: 'setup.exe', size: 4096, score: 35, level: 'MEDIUM', reasons: ['Extension exécutable (exe)'] },
        { index: 1, path: 'readme.txt', size: 300, score: 0, level: 'SAFE', reasons: [] }] });
      document.querySelector('#addScanList .scan-check').checked = false;
      setCatalog({ 'web.units.byte': 'B', 'web.units.kilobyte': 'KB' });
      const rows = [...document.querySelectorAll('#addScanList .scan-row')];
      const seen = rows.map((row) => [row.querySelector('.scan-size').textContent,
        row.querySelector('.scan-reasons').textContent, row.querySelector('.scan-check').checked]);
      addClearScanList();
      addLastScan = null;
      setCatalog({});
      return JSON.stringify(seen);
    })()""")
    assert result == '[["4.0 KB","Executable extension (exe)",false],["300 B","",true]]'


def test_a_start_the_theme_refuses_is_said_in_a_dialog(view):
    """Only the hidden Add page's status line said it, and "Torrent ajouté."
    replaced it at once."""
    result = run_js(view, """(function () {
      setCatalog({ 'cccp.nyet_title': 'Nyet.', 'cccp.download_blocked_message': 'Stays paused.' });
      addShowBlockedByTheme();
      switchToTab('downloads');  // the Add page's "started" handler
      const overlay = document.getElementById('modalOverlay');
      const seen = [overlay.classList.contains('active'), document.querySelector('#modalBox h3').textContent,
                    document.querySelector('#modalBox p').textContent];
      closeModal();
      setCatalog({});
      return JSON.stringify(seen);
    })()""")
    assert result == '[true,"Nyet.","Stays paused."]'


def test_the_share_pages_confirmation_stays_once_a_share_started(view):
    """"started" comes before startShare's answer, which wrote "" over it."""
    result = run_js(view, """(function () {
      const sig = () => { const cbs = []; return { connect: (f) => cbs.push(f), emit: (...a) => cbs.forEach((f) => f(...a)) }; };
      const share = { started: sig(), recordUpdated: sig(), recordsUpdated: sig(), recordRemoved: sig(),
                      defaultDataDir(cb) { cb('C:/data'); }, listTorrents(cb) { cb([]); }, selectTorrentFile() {},
                      startShare(dir, magnet, hours, mb, ratio, cb) { share.started.emit(); cb({ ok: true }); } };
      window.bridge = { share, dialogs: {} };
      setCatalog({ 'web.share.share_started_status': 'Share started.' });
      wireSharePage();
      const status = document.getElementById('shareStatus');
      document.getElementById('shareStartBtn').click();
      const seen = [status.textContent];
      share.startShare = (dir, magnet, hours, mb, ratio, cb) => cb({ ok: false, error: 'Refused.' });
      document.getElementById('shareStartBtn').click();
      seen.push(status.textContent);
      status.textContent = '';
      setCatalog({});
      return JSON.stringify(seen);
    })()""")
    assert result == '["Share started.","Refused."]'
