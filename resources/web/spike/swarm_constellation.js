// Swarm constellation: the local torrent as a fixed dot at the center of a
// canvas, each connected peer as a dot orbiting around it. Mirrors
// peer_list.js/piece_map_dialog.js: polls the bridge on its own 2s timer
// while the dialog is open, poll stops on close.
//
// Encoding (deliberately reuses the app's existing color language --
// green/blue-gray/orange/red already mean have/common/rare/none in
// piece_map_dialog.js, and green/orange already mean download/upload in
// speed_graph_dialog.js):
//   - distance from center = how close the peer is to a complete copy
//     (further along = drawn closer in, like it's joining us at the center)
//   - dot size = that peer's combined download+upload speed
//   - dot color = that peer's progress bucket (seed/half/started/none)

const SWARM_CANVAS_SIZE = 320;
const SWARM_RING_MIN = 40; // px from center for a peer at 100% progress
const SWARM_RING_MAX = 150; // px from center for a peer at 0% progress
const SWARM_LOCAL_RADIUS = 14;
const SWARM_DOT_MIN_RADIUS = 4;
const SWARM_DOT_MAX_RADIUS = 14;
const SWARM_SPEED_SCALE = 12; // sqrt(bytes/s) divisor -- ponytail: tuned by eye, not measured against real swarm speed distributions

const SWARM_COLOR_LOCAL = "#4CAF50";
const SWARM_COLOR_PEER_SEED = "#4CAF50"; // progress 100%
const SWARM_COLOR_PEER_HALF = "#5B7C99"; // progress 50-99%
const SWARM_COLOR_PEER_STARTED = "#E67E22"; // progress 0-50%
const SWARM_COLOR_PEER_NONE = "#C0392B"; // progress 0%
const SWARM_COLOR_ORBIT = "rgba(128,128,128,0.15)";
const SWARM_COLOR_LINK = "rgba(128,128,128,0.2)";

function _swarmPeerColor(progress) {
  if (progress >= 1) return SWARM_COLOR_PEER_SEED;
  if (progress >= 0.5) return SWARM_COLOR_PEER_HALF;
  if (progress > 0) return SWARM_COLOR_PEER_STARTED;
  return SWARM_COLOR_PEER_NONE;
}

function _swarmPeerRadius(peer) {
  const speed = Math.max(0, (peer.downSpeed || 0) + (peer.upSpeed || 0));
  const scaled = Math.sqrt(speed) / SWARM_SPEED_SCALE;
  return Math.min(SWARM_DOT_MAX_RADIUS, SWARM_DOT_MIN_RADIUS + scaled);
}

function _drawSwarmConstellation(ctx, canvas, peers) {
  const w = canvas.width;
  const h = canvas.height;
  const cx = w / 2;
  const cy = h / 2;
  ctx.clearRect(0, 0, w, h);

  ctx.strokeStyle = SWARM_COLOR_ORBIT;
  ctx.lineWidth = 1;
  for (const frac of [1 / 3, 2 / 3, 1]) {
    ctx.beginPath();
    ctx.arc(cx, cy, SWARM_RING_MIN + frac * (SWARM_RING_MAX - SWARM_RING_MIN), 0, Math.PI * 2);
    ctx.stroke();
  }

  const count = peers.length;
  peers.forEach((peer, i) => {
    const progress = Math.min(1, Math.max(0, peer.progress || 0));
    const angle = -Math.PI / 2 + (i / Math.max(1, count)) * Math.PI * 2;
    const radius = SWARM_RING_MIN + (1 - progress) * (SWARM_RING_MAX - SWARM_RING_MIN);
    const x = cx + Math.cos(angle) * radius;
    const y = cy + Math.sin(angle) * radius;

    ctx.strokeStyle = SWARM_COLOR_LINK;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(x, y);
    ctx.stroke();

    ctx.fillStyle = _swarmPeerColor(progress);
    ctx.beginPath();
    ctx.arc(x, y, _swarmPeerRadius(peer), 0, Math.PI * 2);
    ctx.fill();
  });

  // Local torrent drawn last so it sits above the connecting lines.
  ctx.fillStyle = SWARM_COLOR_LOCAL;
  ctx.beginPath();
  ctx.arc(cx, cy, SWARM_LOCAL_RADIUS, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2;
  ctx.stroke();
}

function _swarmLegend() {
  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.gap = "16px";
  row.style.marginTop = "6px";
  row.style.flexWrap = "wrap";

  for (const [color, label] of [
    [SWARM_COLOR_LOCAL, "Vous (local)"],
    [SWARM_COLOR_PEER_SEED, "Pair — copie complète"],
    [SWARM_COLOR_PEER_HALF, "Pair — plus de la moitié"],
    [SWARM_COLOR_PEER_STARTED, "Pair — début"],
    [SWARM_COLOR_PEER_NONE, "Pair — aucune donnée"],
  ]) {
    const item = document.createElement("div");
    item.style.display = "flex";
    item.style.alignItems = "center";
    item.style.gap = "6px";

    const swatch = document.createElement("div");
    swatch.style.width = "10px";
    swatch.style.height = "10px";
    swatch.style.borderRadius = "50%";
    swatch.style.backgroundColor = color;
    item.appendChild(swatch);

    const text = document.createElement("span");
    text.textContent = label;
    item.appendChild(text);

    row.appendChild(item);
  }

  const note = document.createElement("p");
  note.className = "field-note";
  note.textContent = "Taille du point = vitesse totale (↓+↑). Distance = proximité d'une copie complète.";
  row.appendChild(note);

  return row;
}

function openSwarmConstellationDialog(infoHash, torrentName) {
  const contentEl = document.createElement("div");

  const canvas = document.createElement("canvas");
  canvas.width = SWARM_CANVAS_SIZE;
  canvas.height = SWARM_CANVAS_SIZE;
  contentEl.appendChild(canvas);

  const emptyNote = document.createElement("p");
  emptyNote.className = "empty-note";
  emptyNote.textContent = "Aucun pair connecté.";
  emptyNote.style.display = "none";
  contentEl.appendChild(emptyNote);

  contentEl.appendChild(_swarmLegend());

  const ctx = canvas.getContext("2d");

  const refresh = () => {
    window.bridge.swarmConstellation.getPeers(infoHash, (peers) => {
      emptyNote.style.display = peers.length === 0 ? "" : "none";
      _drawSwarmConstellation(ctx, canvas, peers);
    });
  };
  refresh();
  const timer = setInterval(refresh, 2000);

  openModal(`Constellation de l'essaim — ${torrentName}`, contentEl, () => clearInterval(timer));
}
