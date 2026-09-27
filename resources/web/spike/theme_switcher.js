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

function setActiveTheme(themeId) {
  const id = VALID_THEME_IDS.has(themeId) ? themeId : DEFAULT_THEME_ID;
  const link = document.getElementById("themeTokensLink");
  link.onload = syncColorScheme;  // the new sheet resolves asynchronously
  link.href = `themes/${id}/tokens.css`;
  syncColorScheme();
}

// Native widgets (scrollbars, sliders, the text of form fields) follow
// `color-scheme`. Several themes keep a light palette in "dark" or "hc" (no
// dark block, or a white high-contrast mode), so the scheme is read off the
// resolved ink rather than the mode name: light ink means a dark theme.
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

function setAppearanceMode(mode) {
  // tokens.css files define [data-theme="dark"] / [data-theme="hc"]
  // override blocks on top of :root's light-mode base -- "light" itself
  // means no attribute at all.
  const attr = mode === "dark" ? "dark" : mode === "dark_hc" ? "hc" : null;
  if (attr) {
    document.documentElement.setAttribute("data-theme", attr);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  syncColorScheme();
}
