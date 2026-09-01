// Per-torrent piece availability map: one cell per piece, laid out in a
// roughly-square grid. Mirrors peer_list.js/speed_graph_dialog.js: polls
// the bridge on its own timer while the dialog is open, poll stops on close.

const PIECE_MAP_CELL_PX = 8;
const PIECE_MAP_COLOR_HAVE = "#4CAF50"; // same green as the speed graph's download line -- "this data is secured"
const PIECE_MAP_COLOR_MISSING_NONE = "#C0392B"; // no connected peer has this piece at all
const PIECE_MAP_COLOR_MISSING_RARE = "#E67E22"; // same orange as the speed graph's upload line -- a warning-ish "few sources" tone
const PIECE_MAP_COLOR_MISSING_COMMON = "#5B7C99"; // neutral/safe -- plenty of peers have it
const PIECE_MAP_RARE_THRESHOLD = 2; // availability 1-2 peers = "rare", 3+ = "common"

function _pieceMapColor(have, availability) {
  if (have) return PIECE_MAP_COLOR_HAVE;
  if (availability <= 0) return PIECE_MAP_COLOR_MISSING_NONE;
  if (availability <= PIECE_MAP_RARE_THRESHOLD) return PIECE_MAP_COLOR_MISSING_RARE;
  return PIECE_MAP_COLOR_MISSING_COMMON;
}

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
    ctx.fillStyle = _pieceMapColor(have[i], availability[i]);
    ctx.fillRect(col * PIECE_MAP_CELL_PX + 1, row * PIECE_MAP_CELL_PX + 1, PIECE_MAP_CELL_PX - 1, PIECE_MAP_CELL_PX - 1);
  }
}

function _pieceMapLegend() {
  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.gap = "16px";
  row.style.marginTop = "6px";
  row.style.flexWrap = "wrap";

  for (const [color, label] of [
    [PIECE_MAP_COLOR_HAVE, "Téléchargé"],
    [PIECE_MAP_COLOR_MISSING_COMMON, "Manquant (courant)"],
    [PIECE_MAP_COLOR_MISSING_RARE, "Manquant (rare)"],
    [PIECE_MAP_COLOR_MISSING_NONE, "Manquant (aucun pair)"],
  ]) {
    const item = document.createElement("div");
    item.style.display = "flex";
    item.style.alignItems = "center";
    item.style.gap = "6px";

    const swatch = document.createElement("div");
    swatch.style.width = "10px";
    swatch.style.height = "10px";
    swatch.style.backgroundColor = color;
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
      _drawPieceMap(ctx, canvas, Number(canvas.dataset.cols), snapshot, prevSnapshot);
      prevSnapshot = snapshot;
    });
  };
  refresh();
  const timer = setInterval(refresh, 2000);

  openModal(`Mosaïque des morceaux — ${torrentName}`, contentEl, () => clearInterval(timer));
}
