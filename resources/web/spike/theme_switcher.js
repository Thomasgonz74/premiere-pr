// Swaps the active theme's tokens.css and appearance-mode (light/dark/hc)
// attribute -- the whole rest of the app (style.css, downloads.js-built
// markup, every page CSS) consumes only var(--token-name), never a hex
// value directly, so swapping the <link> href is enough to re-skin
// everything live, no page reload needed.

// Matches the folder names under resources/web/spike/themes/. The 7 ids
// that collide with a native theme_id (luna_xp/win7_aero/win10_fluent/
// win11_mica/win95_classic/macos_modern/cccp_soviet) are reused on purpose --
// session_manager.py's CCCP "no downloading" rule and macOS's stats-leveling
// weighting key off those exact strings, so keeping the same id keeps that
// business logic working untouched.
const VALID_THEME_IDS = new Set([
  "luna_xp", "win7_aero", "win10_fluent", "win11_mica", "win95_classic", "macos_modern", "cccp_soviet",
  "amiga-workbench", "art-deco", "bauhaus", "beos-r5", "blueprint", "cde-motif", "chromeos",
  "frutiger-aero", "kde-plasma", "gnome-adwaita", "linux-mint", "macos-9", "macos-x-aqua",
  "macos-x-leopard", "macintosh-system-1", "memphis", "nextstep", "palm-os", "soviet-cosmic",
  "swiss-international", "synthwave", "tui-dos", "terminal-phosphor", "ubuntu", "ubuntu-unity",
  "web-brutalism", "windows-8",
]);

const DEFAULT_THEME_ID = "luna_xp";

// Themes whose tokens.css has no [data-theme="dark"] block: "dark" would show
// their light palette, so the Profile selector offers only light and high
// contrast for them, and a saved "dark" is applied as light while one of them
// is active -- the saved preference itself is kept for the next theme.
// tests/test_theme_css_integrity.py fails if this drifts from the CSS.
const THEMES_WITHOUT_DARK_MODE = new Set([
  "art-deco", "blueprint", "nextstep", "soviet-cosmic", "synthwave", "terminal-phosphor", "tui-dos",
]);

let _activeThemeId = DEFAULT_THEME_ID;  // the theme asked for
let _sheetThemeId = DEFAULT_THEME_ID;   // the theme whose sheet is painted
let _savedAppearanceMode = "light";

function setActiveTheme(themeId) {
  const id = VALID_THEME_IDS.has(themeId) ? themeId : DEFAULT_THEME_ID;
  _activeThemeId = id;
  const link = document.getElementById("themeTokensLink");
  // The new sheet resolves asynchronously and the old one stays painted
  // until then (nothing is painted yet on the very first call), so the
  // mode is settled again once it is in; also syncs the scheme.
  if (!link.sheet) _sheetThemeId = id;
  link.onload = () => {
    _sheetThemeId = id;
    setAppearanceMode(_savedAppearanceMode);
  };
  link.href = `themes/${id}/tokens.css`;
  setAppearanceMode(_savedAppearanceMode);
}

// The mode a theme really shows for a saved appearance mode.
function appliedAppearanceMode(themeId, mode) {
  return mode === "dark" && THEMES_WITHOUT_DARK_MODE.has(themeId) ? "light" : mode;
}

// Native widgets (scrollbars, sliders, the text of form fields) follow
// `color-scheme`. The mode name does not tell: several themes are already
// nocturnal in "light" (those without a dark block) or keep a white
// high-contrast mode, so the scheme is read off the resolved ink rather than
// the mode name: light ink means a dark theme.
// style.css maps data-scheme="dark" to color-scheme: dark.
const _schemeProbe = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
function syncColorScheme() {
  _schemeProbe.clearRect(0, 0, 1, 1);
  _schemeProbe.fillStyle = "#000";
  _schemeProbe.fillStyle = getComputedStyle(document.documentElement).color;
  _schemeProbe.fillRect(0, 0, 1, 1);
  const [r, g, b] = _schemeProbe.getImageData(0, 0, 1, 1).data;
  document.documentElement.dataset.scheme = 0.2126 * r + 0.7152 * g + 0.0722 * b > 128 ? "dark" : "light";
}

// Canvas colours cannot use var(): identicon.js and tetris.js cache the
// resolved tokens and repaint on this event, fired after every mode change --
// including the one setActiveTheme's onload makes once a new sheet is in.
function themeApplied() {
  syncColorScheme();
  document.dispatchEvent(new Event("t2k-themechange"));
}

function setAppearanceMode(mode) {
  _savedAppearanceMode = mode;
  // tokens.css files define [data-theme="dark"] / [data-theme="hc"]
  // override blocks on top of :root's light-mode base -- "light" itself
  // means no attribute at all.
  // "dark" is dropped only when neither the painted sheet nor the one
  // loading has a dark palette: whichever of the two lacks one shows the
  // same pixels with the attribute, so a switch never flashes the painted
  // theme's light palette nor the loaded one's before onload.
  const applied = appliedAppearanceMode(_activeThemeId, mode) === mode ? mode : appliedAppearanceMode(_sheetThemeId, mode);
  const attr = applied === "dark" ? "dark" : applied === "dark_hc" ? "hc" : null;
  if (attr) {
    document.documentElement.setAttribute("data-theme", attr);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  themeApplied();
}
