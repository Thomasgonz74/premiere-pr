"""Page-level readability probe shared by the web-UI theme tests.

Loads resources/web/spike/index.html in a plain QWebEngineView (no Python
bridges, no libtorrent), injects demo data through the pages' own render
functions, and measures what a reader actually sees: text/background contrast
composited over every ancestor background (WCAG ratio), column widths,
horizontal overflow, mosaic scaling, pin state, scan-list rows...

The same scripts drive the manual review harness (tools/theme_review), so a
number seen in a report and a number asserted here come from one definition.
The Profile page is not covered: its content is built from the settings
bridge.
"""

BRIDGE_STUB_JS = r"""
// No QWebChannel here: a stand-in bridge whose every method is a no-op and
// every signal accepts connect(), so the RSS and Search pages can build their
// DOM (their wiring only calls the bridge from event handlers).
(function () {
  const member = new Proxy(function () {}, {
    get: (_, key) => (key === 'connect' || key === 'disconnect') ? (() => {}) : undefined,
    apply: () => undefined,
  });
  window.bridge = new Proxy({}, { get: () => new Proxy({}, { get: () => member }) });
  try { wireRssPage(); } catch (e) { console.error('wire rss', e); }
  try { wireSearchPage(); } catch (e) { console.error('wire search', e); }
})();
"""

INJECT_JS = r"""
(function () {
  try { closeModal(); } catch (e) {}
  const recs = [
    {infoHash: 'aaaa1', name: 'Debian 12 netinst amd64.iso', progress: 0.42, state: 'DOWNLOADING', downloadRate: 1250000, uploadRate: 64000, numPeers: 23, numSeeds: 11, totalSize: 650000000, category: 'Logiciels', healthStatus: 'healthy', pinned: true, locked: false, isPrivate: false, deadline: null},
    {infoHash: 'bbbb2', name: 'Ubuntu 24.04 desktop.iso (miroir lent)', progress: 0.07, state: 'DOWNLOADING', downloadRate: 12000, uploadRate: 0, numPeers: 1, numSeeds: 0, totalSize: 5000000000, category: '', healthStatus: 'warning', pinned: false, locked: false, isPrivate: true, deadline: null},
    {infoHash: 'cccc3', name: 'Archive photos 2019 (verrouillee)', progress: 1.0, state: 'SEEDING', downloadRate: 0, uploadRate: 210000, numPeers: 4, numSeeds: 4, totalSize: 900000000, category: 'Documents', healthStatus: 'critical', pinned: false, locked: true, isPrivate: false, deadline: null},
    {infoHash: 'dddd4', name: 'Torrent en pause', progress: 0.6, state: 'PAUSED', downloadRate: 0, uploadRate: 0, numPeers: 0, numSeeds: 0, totalSize: 100000000, category: '', healthStatus: '', pinned: false, locked: false, isPrivate: false, deadline: null},
    {infoHash: 'ffff6', name: 'Torrent en erreur', progress: 0.3, state: 'ERROR', downloadRate: 0, uploadRate: 0, numPeers: 0, numSeeds: 0, totalSize: 100000000, category: '', healthStatus: '', pinned: false, locked: false, isPrivate: false, deadline: null},
  ];
  recs.forEach(r => { try { downloadsRenderRecord(r); } catch (e) { console.error('inject dl', e); } });
  const shares = [
    {infoHash: 'aaaa1', name: 'Debian 12 netinst amd64.iso', uploadRate: 64000, uploadedBytes: 1200000000, dataLimitBytes: 2000000000, elapsedSeconds: 5400, timeLimitSeconds: 7200, state: 'SEEDING', reached: false, reachedReason: null},
    {infoHash: 'eeee5', name: 'Partage termine (ratio atteint)', uploadRate: 0, uploadedBytes: 3000000000, dataLimitBytes: null, elapsedSeconds: 99999, timeLimitSeconds: null, state: 'PAUSED', reached: true, reachedReason: 'ratio'},
  ];
  shares.forEach(r => { try { shareRenderRow(r); } catch (e) { console.error('inject share', e); } });
  try { const first = document.querySelector('#downloadsList .row'); if (first) { first.classList.add('selected'); } } catch (e) { console.error('select', e); }
  try { showSuggestionBanner('Espace disque faible sur D:\\ (moins de 500 Mo). Envisagez de deplacer ou de supprimer un torrent termine.'); } catch (e) { console.error('banner', e); }
  // keep it for every capture: it auto-hides after 15 s, so its presence depended on run speed
  try { clearTimeout(suggestionBannerTimer); hideSuggestionBanner = function () {}; } catch (e) {}
  try {
    rssFeeds = [{url: 'https://exemple.com/flux.rss', filterKeyword: '1080p', enabled: true, regexInclude: '', regexExclude: '', resolutionMin: 0, resolutionMax: 0, latestEpisodeOnly: false},
                {url: 'https://autre.exemple.org/feed', filterKeyword: '', enabled: false, regexInclude: '', regexExclude: '', resolutionMin: 0, resolutionMax: 0, latestEpisodeOnly: true}];
    rssRenderFeedList();
    rssAppendLog('Exemple de titre 1080p - https://exemple.com/flux.rss', false);
    rssAppendLog('https://autre.exemple.org/feed - erreur de connexion (timeout)', true);
  } catch (e) { console.error('rss', e); }
  try {
    searchSources = [{name: 'Mon indexeur', urlTemplate: 'https://exemple.com/rss?q={query}', enabled: true}, {name: 'Indexeur desactive', urlTemplate: 'https://x.example/{query}', enabled: false}];
    searchRenderSourceList();
    searchRenderResults([{title: 'Resultat exemple 1080p', link: 'magnet:?xt=urn:btih:abc', source: 'Mon indexeur'}, {title: 'Autre resultat (lien http)', link: 'https://exemple.com/a.torrent', source: 'Mon indexeur'}]);
  } catch (e) { console.error('search', e); }
  try {
    addRenderScan({threshold: 50, suggestedDestination: '', fileRisks: [
      {index: 0, path: 'film/Le.Film.2024.1080p.mkv', size: 4200000000, score: 5, level: 'SAFE', reasons: []},
      {index: 1, path: 'film/sous-titres.srt', size: 80000, score: 15, level: 'LOW', reasons: ['extension texte']},
      {index: 2, path: 'film/LISEZMOI.url', size: 300, score: 55, level: 'MEDIUM', reasons: ['raccourci internet']},
      {index: 3, path: 'film/codec_pack.exe', size: 2400000, score: 80, level: 'HIGH', reasons: ['executable Windows', 'nom suspect']},
      {index: 4, path: 'film/crack/keygen.scr', size: 120000, score: 98, level: 'CRITICAL', reasons: ['ecran de veille executable', 'dossier crack']},
    ]});
    const sel = document.getElementById('addSelectedFile'); if (sel) sel.textContent = 'Le.Film.2024.1080p.torrent';
    const st = document.getElementById('addStatus'); if (st) st.textContent = 'Analyse terminee : 5 fichiers, 2 exclus automatiquement.';
  } catch (e) { console.error('scan', e); }
  return 'ok';
})()
"""

# Twelve more plain rows so the Downloads list scrolls in every theme, as it
# does in real use: its vertical scrollbar then takes its share of the width,
# which is when a too-tight grid overflows.
EXTRA_ROWS_JS = r"""
(function () {
  for (let i = 0; i < 12; i++) {
    try {
      downloadsRenderRecord({infoHash: 'extra' + i, name: 'Torrent supplementaire ' + (i + 1), progress: 0.5, state: 'DOWNLOADING',
        downloadRate: 50000, uploadRate: 1000, numPeers: 3, numSeeds: 1, totalSize: 700000000, category: '', healthStatus: '',
        pinned: false, locked: false, isPrivate: false});
    } catch (e) { console.error('extra row', e); }
  }
  return 'ok';
})()
"""

METRICS_JS = r"""
(function () {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  function rgba(str) {
    if (!str || str === 'transparent') return [0, 0, 0, 0];
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = str; cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255];
  }
  function over(top, bot) { const a = top[3]; return [top[0] * a + bot[0] * (1 - a), top[1] * a + bot[1] * (1 - a), top[2] * a + bot[2] * (1 - a), 1]; }
  function gradMean(img) {
    const m = img.match(/(rgba?\([^)]*\)|color\([^)]*\)|#[0-9a-fA-F]{3,8})/g); if (!m) return null;
    const cs = m.map(rgba).filter(c => c[3] > 0.05); if (!cs.length) return null;
    const n = cs.length; return [cs.reduce((s, c) => s + c[0], 0) / n, cs.reduce((s, c) => s + c[1], 0) / n, cs.reduce((s, c) => s + c[2], 0) / n, Math.min(1, cs.reduce((s, c) => s + c[3], 0) / n)];
  }
  function bgOf(el) {
    const chain = []; for (let e = el; e && e.nodeType === 1; e = e.parentElement) chain.push(e);
    let bg = [128, 128, 128, 1];  // harness page background
    for (let i = chain.length - 1; i >= 0; i--) {
      const s = getComputedStyle(chain[i]);
      const img = s.backgroundImage;
      if (img && img !== 'none' && img.indexOf('gradient') !== -1) { const g = gradMean(img); if (g) bg = over(g, bg); }
      const c = rgba(s.backgroundColor); if (c[3] > 0) bg = over(c, bg);
    }
    return bg;
  }
  function lum(c) { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); }
  function ratio(a, b) { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function contrastOf(el) {
    if (!el) return null; const bg = bgOf(el); const fg0 = rgba(getComputedStyle(el).color); const fg = over(fg0, bg);
    return Math.round(ratio(fg, bg) * 100) / 100;
  }
  function minContrast(els) {
    let m = null; els.forEach(el => { if (!el || !el.textContent.trim()) return; const r = contrastOf(el); if (r !== null && (m === null || r < m)) m = r; }); return m;
  }
  const CELLS = '.row-name, .row-state, .row-rate, .row-eta, .row-peers, .row-category';
  function rowMin(sel) { const row = document.querySelector(sel); return row ? minContrast(Array.from(row.querySelectorAll(CELLS))) : null; }
  const R = {};
  R.dl_selected_min = rowMin('#downloadsList .row.selected');
  R.dl_warning_min = rowMin('#downloadsList .row[data-health="warning"]');
  R.dl_critical_min = rowMin('#downloadsList .row[data-health="critical"]');
  R.dl_plain_min = rowMin('#downloadsList .row[data-health=""]');
  const names = Array.from(document.querySelectorAll('#downloadsList .row .row-name'));
  R.dl_name_min_width = names.length ? Math.min.apply(null, names.map(n => n.getBoundingClientRect().width)) : null;
  { const dl = document.querySelector('#downloadsList'); R.dl_overflow_px = dl ? dl.scrollWidth - dl.clientWidth : null; }
  { const row = document.querySelector('#downloadsList .downloads-row'); const dl = document.querySelector('#downloadsList');
    if (row) { const cs = getComputedStyle(row); R.dl_tracks = cs.gridTemplateColumns; R.dl_gap = cs.columnGap; R.dl_row_inner = row.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight); }
    const wraps = {}; document.querySelectorAll('#downloadsList .downloads-row').forEach(r => ['.row-eta', '.row-rate', '.row-peers', '.row-state'].forEach(sel => r.querySelectorAll(sel).forEach(c => { const lh = parseFloat(getComputedStyle(c).lineHeight) || (parseFloat(getComputedStyle(c).fontSize) * 1.3); if (c.textContent.trim() && c.getBoundingClientRect().height > lh * 1.5) wraps[sel] = (wraps[sel] || 0) + 1; })));
    R.dl_wrapped_cells = wraps; }
  { const pins = Array.from(document.querySelectorAll('#downloadsList .row-pin-btn'));
    R.pin_active_filtered = pins.filter(p => p.classList.contains('active') && getComputedStyle(p).filter !== 'none').length;
    R.pin_idle_unfiltered = pins.filter(p => !p.classList.contains('active') && getComputedStyle(p).filter === 'none').length;
    R.pin_active_count = pins.filter(p => p.classList.contains('active')).length; }
  R.tetris_rescaled = Array.from(document.querySelectorAll('#downloadsList canvas.tetris')).filter(c => c.width !== c.clientWidth || c.height !== c.clientHeight).length;
  R.share_name = contrastOf(document.querySelector('#shareList .row .row-name'));
  R.rss_keyword = contrastOf(document.querySelector('#rssFeedList .rss-feed-row > span:not(.row-name)'));
  R.search_result_source = contrastOf(document.querySelector('#searchResultsList .row > span:not(.row-name)'));
  R.rss_error = contrastOf(document.querySelector('.rss-log-error'));
  R.field_note = contrastOf(document.querySelector('.field-note'));
  R.status_line = contrastOf(document.querySelector('.status-line'));
  R.drop_zone = contrastOf(document.querySelector('.drop-zone'));
  R.scan_reasons = contrastOf(document.querySelector('.scan-reasons'));
  R.info_hint = contrastOf(document.querySelector('.info-hint'));
  R.profile_checkbox_label = contrastOf(document.querySelector('#profileGeneralContainer label span, #profileGeneralContainer label'));
  // A mosaic = an url() (icon) layer that tiles. Gradient layers repeating
  // are harmless (they already fill the box), so layers are paired up.
  R.form_select_mosaic = Array.from(document.querySelectorAll('.form-grid select')).filter(s => {
    const cs = getComputedStyle(s);
    const imgs = cs.backgroundImage.split(/,(?![^(]*\))/).map(x => x.trim());
    const reps = cs.backgroundRepeat.split(',').map(x => x.trim());
    return imgs.some((img, i) => img.startsWith('url(') && !/no-repeat/.test(reps[i % reps.length]));
  }).length;
  R.form_select_no_image = Array.from(document.querySelectorAll('.form-grid select')).filter(s => getComputedStyle(s).backgroundImage === 'none').length;
  try { alertModal('Titre', 'Message de test du dialogue', 'OK'); R.modal_msg = contrastOf(document.querySelector('.modal-box p')); closeModal(); } catch (e) { R.modal_msg = 'ERR ' + e; }
  try { const h = document.querySelector('#page-downloads .info-hint'); if (h) { showInfoTooltip(h); R.tooltip = contrastOf(document.querySelector('.info-tooltip-bubble')); hideInfoTooltip(); } } catch (e) { R.tooltip = 'ERR ' + e; }
  try {
    switchToTab('add');
    const list = document.getElementById('addScanList'); const lr = list.getBoundingClientRect();
    R.scan_visible_rows = Array.from(list.querySelectorAll('.scan-row')).filter(r => { const b = r.getBoundingClientRect(); return b.bottom > lr.top + b.height / 2 && b.top < lr.bottom - b.height / 2; }).length;
    const page = document.getElementById('page-add'); const sb = document.getElementById('addStartBtn').getBoundingClientRect();
    const ps = getComputedStyle(page);
    R.start_reachable = (sb.bottom <= window.innerHeight + 1) || (page.scrollHeight > page.clientHeight + 1 && /(auto|scroll)/.test(ps.overflowY));
    switchToTab('downloads');
  } catch (e) { R.scan_visible_rows = 'ERR ' + e; }
  return JSON.stringify(R);
})()
"""

CONTRAST_METRICS = (
    "dl_selected_min", "dl_warning_min", "dl_critical_min", "dl_plain_min",
    "share_name", "rss_keyword", "search_result_source", "rss_error",
    "field_note", "status_line", "drop_zone", "scan_reasons", "info_hint",
    "modal_msg", "tooltip",
)


def failures(m: dict) -> list[str]:
    """Human-readable list of every metric below its bar (None = not measured)."""
    out = []
    for key in CONTRAST_METRICS:
        v = m.get(key)
        if v is None or isinstance(v, str):
            out.append(f"{key}: not measured ({v!r})")
        elif v < 4.5:
            out.append(f"{key}: contrast {v}:1 < 4.5:1")
    checks = [
        ("dl_name_min_width", lambda v: v >= 40, "name column narrower than 40 px"),
        ("dl_overflow_px", lambda v: v == 0, "Downloads grid overflows horizontally"),
        ("tetris_rescaled", lambda v: v == 0, "progress mosaic rescaled by CSS (blurred grid)"),
        ("pin_active_filtered", lambda v: v == 0, "pinned row's pin greyed out"),
        ("pin_idle_unfiltered", lambda v: v == 0, "unpinned pin not greyed"),
        ("form_select_mosaic", lambda v: v == 0, "select background tiled into a mosaic"),
        ("scan_visible_rows", lambda v: v >= 5, "fewer than 5 scan rows visible"),
        ("start_reachable", lambda v: v is True, "Start button unreachable"),
    ]
    for key, ok, what in checks:
        v = m.get(key)
        if v is None or isinstance(v, str) or not ok(v):
            out.append(f"{key} = {v!r}: {what}")
    return out


# ---------------------------------------------------------------- Qt helpers
# Deterministic page driving for the theme tests: no fixed sleeps, no CSS
# transitions (several themes fade colours over 150 ms, and a grab or a
# getComputedStyle mid-fade reads an in-between colour).

NO_MOTION_JS = r"""
(function () {
  if (!document.getElementById('t2k-test-no-motion')) {
    const s = document.createElement('style');
    s.id = 't2k-test-no-motion';
    s.textContent = '*, *::before, *::after { transition: none !important; animation: none !important; }';
    document.head.appendChild(s);
  }
  return 'ok';
})()
"""

TIMEOUT_MS = 10_000


def run_js(view, code: str, timeout_ms: int = TIMEOUT_MS):
    from PySide6.QtTest import QTest

    box: dict = {}
    view.page().runJavaScript(code, 0, lambda r: box.setdefault("r", r))
    waited = 0
    while "r" not in box and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20
    assert "r" in box, f"JavaScript did not answer within {timeout_ms} ms: {code[:80]!r}"
    return box["r"]


def wait_until(view, condition_js: str, timeout_ms: int = TIMEOUT_MS) -> None:
    from PySide6.QtTest import QTest

    waited = 0
    while not run_js(view, condition_js) and waited < timeout_ms:
        QTest.qWait(30)
        waited += 30
    assert waited < timeout_ms, f"timed out waiting for {condition_js!r}"


def settle(view) -> None:
    """Two animation frames: style, layout, ResizeObservers and paint done."""
    run_js(view, "window.__t2kFrames = 0; requestAnimationFrame(() => requestAnimationFrame(() => { window.__t2kFrames = 2; })); true")
    wait_until(view, "window.__t2kFrames === 2")


def set_theme(view, theme_id: str) -> None:
    """setActiveTheme() swaps the <link>; waits for the new sheet to load."""
    run_js(view, f"""(function () {{
      const link = document.getElementById('themeTokensLink');
      window.__t2kThemeLoaded = false;
      if (link.href.endsWith('/themes/{theme_id}/tokens.css') && link.sheet) {{ window.__t2kThemeLoaded = true; }}
      else link.addEventListener('load', () => {{ window.__t2kThemeLoaded = true; }}, {{once: true}});
      setActiveTheme({theme_id!r});
      return true;
    }})()""")
    wait_until(view, "window.__t2kThemeLoaded === true")
    settle(view)


def set_mode(view, mode: str) -> None:
    run_js(view, f"setAppearanceMode({mode!r}); true")
    settle(view)
