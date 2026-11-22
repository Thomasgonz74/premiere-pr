// CCCP theme's propaganda side panel -- port of ui/widgets/propaganda_panel.py.
// Cycles through 18 tongue-in-cheek messages (shuffled order, no immediate
// repeat of the same shuffle pass), each paired with one of 8 hand-drawn
// icons rendered once from the real Python paint routines (see
// scratchpad/generate_propaganda_icons.py) and recolored live via CSS
// mask-image + background-color, exactly like the native _PropagandaIcon's
// single-color repaint but without re-deriving the bezier/polygon math in
// JS. Message text is routed through the i18n catalog (see i18n.js); the
// French originals are Soviet-satire wordplay that may not translate
// cleanly to other languages, and that's expected.

const PROPAGANDA_MESSAGE_INTERVAL_MS = 17000;

// Catalog keys, not t() results: this runs at script load, before the
// catalog arrives (t() would return the raw keys for the whole session).
const PROPAGANDA_MESSAGE_SPECS = [
  ["star", "web.propaganda_panel.message_01"],
  ["hammer_sickle", "web.propaganda_panel.message_02"],
  ["gear", "web.propaganda_panel.message_03"],
  ["sun_rays", "web.propaganda_panel.message_04"],
  ["wheat", "web.propaganda_panel.message_05"],
  ["rocket", "web.propaganda_panel.message_06"],
  ["factory", "web.propaganda_panel.message_07"],
  ["fist", "web.propaganda_panel.message_08"],
  ["star", "web.propaganda_panel.message_09"],
  ["hammer_sickle", "web.propaganda_panel.message_10"],
  ["gear", "web.propaganda_panel.message_11"],
  ["sun_rays", "web.propaganda_panel.message_12"],
  ["wheat", "web.propaganda_panel.message_13"],
  ["rocket", "web.propaganda_panel.message_14"],
  ["factory", "web.propaganda_panel.message_15"],
  ["fist", "web.propaganda_panel.message_16"],
  ["star", "web.propaganda_panel.message_17"],
  ["hammer_sickle", "web.propaganda_panel.message_18"],
];

let _propagandaOrder = [];
let _propagandaPosition = -1;
let _propagandaTimer = null;

function _shuffledIndices(n) {
  const arr = Array.from({ length: n }, (_, i) => i);
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function _showNextPropagandaMessage() {
  _propagandaPosition += 1;
  if (_propagandaPosition >= _propagandaOrder.length) {
    _propagandaPosition = 0;
    _propagandaOrder = _shuffledIndices(PROPAGANDA_MESSAGE_SPECS.length);
  }
  const [kind, key] = PROPAGANDA_MESSAGE_SPECS[_propagandaOrder[_propagandaPosition]];
  const iconEl = document.getElementById("propagandaIcon");
  iconEl.style.maskImage = `url("assets/propaganda/${kind}.png")`;
  iconEl.style.webkitMaskImage = `url("assets/propaganda/${kind}.png")`;
  // Tagged so setCatalog() retranslates it: the panel can start before the
  // catalog arrives (app.js), and the language can change mid-message.
  const messageEl = document.getElementById("propagandaMessage");
  messageEl.dataset.i18nKey = key;
  messageEl.textContent = t(key);
}

function startPropagandaPanel() {
  document.getElementById("cccpPropagandaPanel").hidden = false;
  _propagandaOrder = _shuffledIndices(PROPAGANDA_MESSAGE_SPECS.length);
  _propagandaPosition = -1;
  _showNextPropagandaMessage();
  if (_propagandaTimer) clearInterval(_propagandaTimer);
  _propagandaTimer = setInterval(_showNextPropagandaMessage, PROPAGANDA_MESSAGE_INTERVAL_MS);
}

function stopPropagandaPanel() {
  document.getElementById("cccpPropagandaPanel").hidden = true;
  if (_propagandaTimer) {
    clearInterval(_propagandaTimer);
    _propagandaTimer = null;
  }
}
