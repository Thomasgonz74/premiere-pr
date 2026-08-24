// Per-torrent storage breakdown: a sunburst (concentric-ring) view of disk
// space by file. One ring of file arcs sized by file.size; if the torrent
// has real subfolders, an inner ring of folder arcs is added too (each
// folder's angular span matching the sum of its files' spans). Mirrors
// piece_map_dialog.js/swarm_constellation.js: polls the bridge on its own
// timer while the dialog is open, poll stops on close.
//
// Color = download state, not extension -- reuses the app's existing
// have/missing color language from piece_map_dialog.js (green/orange/red),
// applied per file (and, for the folder ring, per folder's aggregate
// progress) rather than per piece.

const SUNBURST_CANVAS_SIZE = 320;
const SUNBURST_HOLE_RADIUS = 40;
const SUNBURST_RING_WIDTH = 55;
const SUNBURST_COLOR_DONE = "#4CAF50"; // fully downloaded -- same green as piece map's "have"
const SUNBURST_COLOR_PARTIAL = "#E67E22"; // some bytes downloaded, not all
const SUNBURST_COLOR_MISSING = "#C0392B"; // nothing downloaded yet
const SUNBURST_COLOR_STROKE = "rgba(0,0,0,0.15)";

function _sunburstColor(downloaded, size) {
  if (size === 0 || downloaded >= size) return SUNBURST_COLOR_DONE;
  if (downloaded > 0) return SUNBURST_COLOR_PARTIAL;
  return SUNBURST_COLOR_MISSING;
}

function _sunburstDrawArc(ctx, cx, cy, r0, r1, a0, a1, color) {
  ctx.beginPath();
  ctx.arc(cx, cy, r1, a0, a1);
  ctx.arc(cx, cy, r0, a1, a0, true);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.strokeStyle = SUNBURST_COLOR_STROKE;
  ctx.lineWidth = 1;
  ctx.stroke();
}

// Groups files by their top-level path segment. Only called when at least
// one file path actually contains a separator -- a loose top-level file
// (no folder) is bucketed under a synthetic "(racine)" group so every file
// still gets a folder-ring parent.
function _sunburstGroupByFolder(files) {
  const folders = new Map();
  for (const f of files) {
    const segments = f.path.split(/[\\/]/);
    const name = segments.length > 1 ? segments[0] : "(racine)";
    let folder = folders.get(name);
    if (!folder) {
      folder = { size: 0, downloaded: 0, files: [] };
      folders.set(name, folder);
    }
    folder.size += f.size;
    folder.downloaded += Math.min(f.downloaded, f.size);
    folder.files.push(f);
  }
  return [...folders.values()];
}

function _drawSunburst(ctx, canvas, files) {
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const totalSize = files.reduce((sum, f) => sum + f.size, 0);
  if (totalSize === 0) return;

  const hasNesting = files.some((f) => /[\\/]/.test(f.path));
  const r0 = SUNBURST_HOLE_RADIUS;
  const r1 = SUNBURST_HOLE_RADIUS + SUNBURST_RING_WIDTH;

  if (!hasNesting) {
    let angle = -Math.PI / 2;
    for (const f of files) {
      const span = (f.size / totalSize) * Math.PI * 2;
      _sunburstDrawArc(ctx, cx, cy, r0, r1, angle, angle + span, _sunburstColor(f.downloaded, f.size));
      angle += span;
    }
    return;
  }

  const r2 = r1 + SUNBURST_RING_WIDTH;
  let angle = -Math.PI / 2;
  for (const folder of _sunburstGroupByFolder(files)) {
    const folderSpan = (folder.size / totalSize) * Math.PI * 2;
    _sunburstDrawArc(ctx, cx, cy, r0, r1, angle, angle + folderSpan, _sunburstColor(folder.downloaded, folder.size));

    let fileAngle = angle;
    for (const f of folder.files) {
      const fileSpan = folder.size > 0 ? (f.size / folder.size) * folderSpan : 0;
      _sunburstDrawArc(ctx, cx, cy, r1, r2, fileAngle, fileAngle + fileSpan, _sunburstColor(f.downloaded, f.size));
      fileAngle += fileSpan;
    }
    angle += folderSpan;
  }
}

function _sunburstLegend() {
  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.gap = "16px";
  row.style.marginTop = "6px";
  row.style.flexWrap = "wrap";

  for (const [color, label] of [
    [SUNBURST_COLOR_DONE, "Téléchargé"],
    [SUNBURST_COLOR_PARTIAL, "Partiel"],
    [SUNBURST_COLOR_MISSING, "Manquant"],
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

  const note = document.createElement("p");
  note.className = "field-note";
  note.textContent = "Chaque secteur = un fichier, proportionnel à sa taille. Anneau intérieur = dossiers (si le torrent en a).";
  row.appendChild(note);

  return row;
}

function openStorageSunburstDialog(infoHash, torrentName) {
  const contentEl = document.createElement("div");

  const canvas = document.createElement("canvas");
  canvas.width = SUNBURST_CANVAS_SIZE;
  canvas.height = SUNBURST_CANVAS_SIZE;
  contentEl.appendChild(canvas);

  const emptyNote = document.createElement("p");
  emptyNote.className = "empty-note";
  emptyNote.textContent =
    "Aucune information de fichiers disponible pour le moment (métadonnées non reçues, ou torrent introuvable).";
  emptyNote.style.display = "none";
  contentEl.appendChild(emptyNote);

  contentEl.appendChild(_sunburstLegend());

  const ctx = canvas.getContext("2d");

  const refresh = () => {
    window.bridge.storageSunburst.getFileBreakdown(infoHash, (files) => {
      const empty = files.length === 0;
      canvas.style.display = empty ? "none" : "";
      emptyNote.style.display = empty ? "" : "none";
      if (!empty) _drawSunburst(ctx, canvas, files);
    });
  };
  refresh();
  const timer = setInterval(refresh, 2000);

  openModal(`Répartition du stockage — ${torrentName}`, contentEl, () => clearInterval(timer));
}
