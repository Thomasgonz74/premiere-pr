// Phase 0 spike wiring: QWebChannel bridge hookup, window drag/resize via
// the Python-side WindowBridge (native startSystemMove/startSystemResize --
// see docs/plan notes on why this can't just be a plain CSS drag region
// under QtWebEngine). Downloads-page rendering itself lives in downloads.js.

function wireWindowChrome(windowBridge) {
  // Guards against a second mousedown arriving mid-gesture (observed while
  // testing with synthetic input; startSystemMove() hands the current
  // press off to the OS move-loop, and a stray re-delivered mousedown
  // before the matching mouseup would otherwise re-enter it).
  let dragging = false;
  document.getElementById("dragRegion").addEventListener("mousedown", (event) => {
    if (event.button !== 0 || dragging) return;
    // Without this, Chromium starts its own text-selection drag on the
    // press before startMove() hands the gesture to the OS move-loop; the
    // matching mouseup then never reaches the page (captured natively
    // instead), leaving that selection dangling -- observed as the whole
    // page's text ending up highlighted after a move/resize.
    event.preventDefault();
    dragging = true;
    windowBridge.startMove();
  });
  document.addEventListener("mouseup", () => {
    dragging = false;
  });
  document.getElementById("dragRegion").addEventListener("dblclick", () => {
    windowBridge.toggleMaximize();
  });
  document.getElementById("btnMin").addEventListener("click", () => windowBridge.minimize());
  document.getElementById("btnMax").addEventListener("click", () => windowBridge.toggleMaximize());
  document.getElementById("btnClose").addEventListener("click", () => windowBridge.close());

  document.querySelectorAll(".resize-edge, .resize-corner").forEach((el) => {
    el.addEventListener("mousedown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault(); // same fix as dragRegion above -- see comment there
      windowBridge.startResize(el.dataset.edge);
    });
  });
}

// CCCP is one of the 7 theme ids reused verbatim from the native app on
// purpose (see theme_switcher.js) -- the propaganda panel/anthem toggle key
// off this exact string, same as session_manager.py's download-block rule.
function _applyCccpPanelState(themeId, windowBridge) {
  const active = themeId === "cccp_soviet";
  windowBridge.setPropagandaPanelActive(active);
  if (active) {
    startPropagandaPanel();
  } else {
    stopPropagandaPanel();
  }
}

new QWebChannel(qt.webChannelTransport, (channel) => {
  window.bridge = channel.objects;
  wireWindowChrome(channel.objects.windowBridge);

  // Applies the theme/appearance-mode already saved in Settings on load
  // (the <link> in index.html only has a hardcoded default for the first
  // paint before the bridge is ready), then keeps it live-synced with the
  // Profile > General page's selectors for the rest of the session.
  channel.objects.profileGeneral.getSettings((s) => {
    setActiveTheme(s.theme);
    setAppearanceMode(s.appearanceMode);
    _applyCccpPanelState(s.theme, channel.objects.windowBridge);
  });
  channel.objects.profileGeneral.themeChanged.connect((themeId, mode) => {
    setActiveTheme(themeId);
    setAppearanceMode(mode);
    _applyCccpPanelState(themeId, channel.objects.windowBridge);
  });

  // Re-fetch the fallback-resolved catalog (see i18n.js/bridge_i18n.py) and
  // refresh static DOM whenever the Profile > General language selector
  // changes it -- dynamically-rendered content (list rows, dialogs) needs
  // no extra wiring here, it already calls t() fresh on its own next render.
  channel.objects.profileGeneral.languageChanged.connect(() => {
    channel.objects.i18n.getCatalog((catalog) => setCatalog(catalog));
  });

  // One-time welcome dialog on the very first launch (see
  // window_bridge.shouldShowOnboarding/markOnboardingSeen -- backed by
  // Settings.first_launch_seen, same flag the native app uses).
  channel.objects.windowBridge.shouldShowOnboarding((show) => {
    if (!show) return;
    alertModal(
      t("onboarding.title"),
      t("onboarding.message"),
      t("onboarding.ok_button"),
      () => channel.objects.windowBridge.markOnboardingSeen()
    );
  });

  // Catalogue idea "detection de lien magnet dans le presse-papiers" (off
  // by default, see Profil > Automatisation) -- never auto-adds, always
  // offers first.
  channel.objects.windowBridge.magnetDetected.connect((magnetUri) => {
    if (confirm(t("web.app.magnet_detected_confirm", { magnetUri }))) {
      switchToTab("add");
      channel.objects.add.analyzeMagnet(magnetUri);
    }
  });

  channel.objects.update.updateAvailable.connect((version, releaseUrl) => {
    showUpdateAvailable(version, releaseUrl);
  });
  channel.objects.update.installerVerified.connect((localPath) => {
    showInstallerVerified(localPath);
  });

  // Note: no JS-side countdownStarted.connect() here -- spike_window.py's
  // _on_shutdown_countdown_started already calls showAutoShutdownCountdown()
  // directly via runJavaScript with the action already resolved from
  // settings; connecting again here would fire the dialog twice.

  // Pages are built with t() calls baked into their DOM construction, so
  // they must wire up only after the catalog has actually arrived --
  // otherwise every label would render as its raw key.
  channel.objects.i18n.getCatalog((catalog) => {
    setCatalog(catalog);

    wireDownloadsPage();
    wireAddPage();
    wireSharePage();
    wireRssPage();
    wireSearchPage();
    wireProfileGeneral();
    wireProfileNetwork();
    wireProfileAutomation();
    wireProfileSecurity();
    wireProfileAdvanced();
    wireProfileStats();
  });
});
