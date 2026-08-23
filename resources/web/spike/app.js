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

  // One-time welcome dialog on the very first launch (see
  // window_bridge.shouldShowOnboarding/markOnboardingSeen -- backed by
  // Settings.first_launch_seen, same flag the native app uses).
  channel.objects.windowBridge.shouldShowOnboarding((show) => {
    if (!show) return;
    alertModal(
      "Bienvenue dans Torrent 2000",
      "Avant de commencer, faites un tour dans l'onglet Profil : vous y trouverez les réglages de confidentialité et de réseau (proxy, chiffrement, découverte réseau) qui déterminent ce que vos pairs peuvent voir de votre activité.",
      "Compris",
      () => channel.objects.windowBridge.markOnboardingSeen()
    );
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

  wireDownloadsPage();
  wireAddPage();
  wireSharePage();
  wireRssPage();
  wireProfileGeneral();
  wireProfileNetwork();
  wireProfileAutomation();
  wireProfileSecurity();
  wireProfileAdvanced();
  wireProfileStats();
});
