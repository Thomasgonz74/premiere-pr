// Per-torrent piece availability map: one cell per piece, laid out in a
// roughly-square grid. Mirrors peer_list.js/speed_graph_dialog.js: polls
// the bridge on its own timer while the dialog is open, poll stops on close.

const PIECE_MAP_CELL_PX = 8;
const PIECE_MAP_RARE_THRESHOLD = 2; // availability 1-2 peers = "rare", 3+ = "common"

// Colours of the four data dialogs (piece map, speed graph, swarm, sunburst):
// optional theme tokens (style.css, "Optional theme tokens"), each with its
// stock colour or the token it follows when unset -- the dialogs share one
// colour language on purpose (green have/download, blue-grey common, orange
// rare/upload, red none).
const DATA_COLORS = {
  "--piece-have": "#4CAF50", // "this data is secured"
  "--piece-common": "#5B7C99", // neutral/safe -- plenty of peers have it
  "--piece-rare": "#E67E22", // a warning-ish "few sources" tone
  "--piece-none": "#C0392B", // no connected peer has this piece at all
  "--speed-down": "--piece-have",
  "--speed-up": "--piece-rare",
  "--speed-grid": "rgba(128,128,128,0.24)",
  "--speed-axis": "#808080",
  "--swarm-local": "--piece-have",
  "--swarm-seed": "--piece-have", // progress 100%
  "--swarm-half": "--piece-common", // progress 50-99%
  "--swarm-started": "--piece-rare", // progress 0-50%
  "--swarm-none": "--piece-none", // progress 0%
  "--swarm-ring": "#ffffff", // round the local node
  "--swarm-orbit": "rgba(128,128,128,0.15)",
  "--swarm-link": "rgba(128,128,128,0.2)",
  "--sunburst-done": "--piece-have", // fully downloaded
  "--sunburst-partial": "--piece-rare", // some bytes downloaded, not all
  "--sunburst-missing": "--piece-none", // nothing downloaded yet
  "--sunburst-stroke": "rgba(0,0,0,0.15)",
};

// A canvas fill cannot take var(): resolved once per theme/mode, like
// tetris.js. Each open dialog repaints on t2k-themechange.
const _dataColorCache = new Map();
document.addEventListener("t2k-themechange", () => _dataColorCache.clear());
function dataColor(name) {
  let color = _dataColorCache.get(name);
  if (color === undefined) {
    const stock = DATA_COLORS[name];
    color = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
      || (stock.startsWith("--") ? dataColor(stock) : stock);
    _dataColorCache.set(name, color);
  }
  return color;
}

// Legend swatches are DOM: var() keeps them in step with the theme unaided.
function dataColorVar(name) {
  const stock = DATA_COLORS[name];
  return `var(${name}, ${stock.startsWith("--") ? dataColorVar(stock) : stock})`;
}

function _pieceMapColor(have, availability) {
  if (have) return dataColor("--piece-have");
  if (availability <= 0) return dataColor("--piece-none");
  if (availability <= PIECE_MAP_RARE_THRESHOLD) return dataColor("--piece-rare");
  return dataColor("--piece-common");
}

// `have` and `availability` are strings, one char per piece (see
// bridge_piece_map.py): "1"/"0", and a peer count capped at "9". Decode
// have[i] === "1" -- the string "0" is truthy.
function _drawPieceMap(ctx, canvas, cols, snapshot, prevSnapshot) {
  const { numPieces, have, availability } = snapshot;
  for (let i = 0; i < numPieces; i++) {
    // Skip repainting a cell whose color hasn't changed since the last
    // poll -- most cells are stable between two polls (a "have" piece
    // never reverts, and availability moves slowly), so this avoids
    // thousands of redundant fillRect calls per refresh on a large torrent.
    if (prevSnapshot && prevSnapshot.have[i] === have[i] && prevSnapshot.availability[i] === availability[i]) {
      continue;
    }
    const row = Math.floor(i / cols);
    const col = i % cols;
    ctx.fillStyle = _pieceMapColor(have[i] === "1", Number(availability[i]));
    ctx.fillRect(col * PIECE_MAP_CELL_PX + 1, row * PIECE_MAP_CELL_PX + 1, PIECE_MAP_CELL_PX - 1, PIECE_MAP_CELL_PX - 1);
  }
}

function _pieceMapLegend() {
  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.gap = "16px";
  row.style.marginTop = "6px";
  row.style.flexWrap = "wrap";

  for (const [token, label] of [
    ["--piece-have", t("profile_tab.history_column_downloaded")],
    ["--piece-common", t("web.piece_map_dialog.legend_missing_common")],
    ["--piece-rare", t("web.piece_map_dialog.legend_missing_rare")],
    ["--piece-none", t("web.piece_map_dialog.legend_missing_none")],
  ]) {
    const item = document.createElement("div");
    item.style.display = "flex";
    item.style.alignItems = "center";
    item.style.gap = "6px";

    const swatch = document.createElement("div");
    swatch.style.width = "10px";
    swatch.style.height = "10px";
    swatch.style.backgroundColor = dataColorVar(token);
    item.appendChild(swatch);

    const text = document.createElement("span");
    text.textContent = label;
    item.appendChild(text);

    row.appendChild(item);
  }
  return row;
}

function openPieceMapDialog(infoHash, torrentName) {
  const contentEl = document.createElement("div");

  const canvas = document.createElement("canvas");
  canvas.className = "tetris"; // reuse the existing pixelated/bordered canvas look
  canvas.width = 1;
  canvas.height = 1;
  contentEl.appendChild(canvas);
  contentEl.appendChild(_pieceMapLegend());

  const ctx = canvas.getContext("2d");
  let sizedForCount = -1;
  let prevSnapshot = null;

  const refresh = () => {
    window.bridge.pieceMap.getPieceAvailability(infoHash, (snapshot) => {
      const numPieces = snapshot.numPieces || 0;
      if (numPieces === 0) return; // metadata not ready yet -- keep last render
      if (numPieces !== sizedForCount) {
        const cols = Math.max(1, Math.ceil(Math.sqrt(numPieces)));
        const rows = Math.ceil(numPieces / cols);
        canvas.width = cols * PIECE_MAP_CELL_PX;
        canvas.height = rows * PIECE_MAP_CELL_PX;
        sizedForCount = numPieces;
        canvas.dataset.cols = cols;
        prevSnapshot = null; // resizing clears the canvas -- force a full repaint
      }
      // Nothing changed since the last poll (always the case while seeding).
      if (prevSnapshot && prevSnapshot.have === snapshot.have && prevSnapshot.availability === snapshot.availability) {
        return;
      }
      _drawPieceMap(ctx, canvas, Number(canvas.dataset.cols), snapshot, prevSnapshot);
      prevSnapshot = snapshot;
    });
  };
  refresh();
  const timer = setInterval(refresh, 2000);
  // Only changed cells are repainted: a new palette needs every one.
  const repaint = () => { prevSnapshot = null; refresh(); };
  document.addEventListener("t2k-themechange", repaint);

  openModal(t("web.piece_map_dialog.dialog_title", { name: torrentName }), contentEl, () => {
    clearInterval(timer);
    document.removeEventListener("t2k-themechange", repaint);
  });
}
