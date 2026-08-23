// Per-torrent download/upload speed-over-time graph. Mirrors
// ui/dialogs/speed_graph_dialog.py + ui/widgets/speed_graph.py: same colors,
// same 3-line grid, same divide-by-zero floor -- drawn on <canvas> instead
// of QPainter, polled every second while the modal is open.

const SPEED_GRAPH_COLOR_DOWNLOAD = "#4CAF50";
const SPEED_GRAPH_COLOR_UPLOAD = "#E67E22";
const SPEED_GRAPH_COLOR_GRID = "rgba(128,128,128,0.24)";
const SPEED_GRAPH_COLOR_AXIS_TEXT = "#808080";
const SPEED_GRAPH_MARGIN_LEFT = 40;

function _drawSpeedGraph(ctx, width, height, history) {
  ctx.clearRect(0, 0, width, height);

  const plotLeft = SPEED_GRAPH_MARGIN_LEFT;
  const plotWidth = Math.max(1, width - plotLeft);
  const plotTop = 4;
  const plotHeight = Math.max(1, height - plotTop * 2);
  const plotBottom = plotTop + plotHeight;

  let maxRate = 1; // floor avoids divide-by-zero when history is all-idle
  for (const [down, up] of history) {
    maxRate = Math.max(maxRate, down, up);
  }

  ctx.font = "10px sans-serif";
  ctx.fillStyle = SPEED_GRAPH_COLOR_AXIS_TEXT;
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  ctx.strokeStyle = SPEED_GRAPH_COLOR_GRID;
  ctx.lineWidth = 1;

  for (const fraction of [0, 0.5, 1.0]) {
    const y = plotBottom - fraction * plotHeight;
    ctx.beginPath();
    ctx.moveTo(plotLeft, y);
    ctx.lineTo(width, y);
    ctx.stroke();
    ctx.fillText(formatRate(maxRate * fraction), plotLeft - 4, y);
  }

  if (history.length >= 2) {
    _drawSpeedCurve(ctx, history, 0, maxRate, plotLeft, plotWidth, plotTop, plotHeight, SPEED_GRAPH_COLOR_DOWNLOAD);
    _drawSpeedCurve(ctx, history, 1, maxRate, plotLeft, plotWidth, plotTop, plotHeight, SPEED_GRAPH_COLOR_UPLOAD);
  }
}

function _drawSpeedCurve(ctx, history, index, maxRate, plotLeft, plotWidth, plotTop, plotHeight, color) {
  const count = history.length;
  const step = plotWidth / (count - 1);

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  history.forEach((sample, i) => {
    const value = sample[index];
    const x = plotLeft + i * step;
    const fraction = Math.min(1, value / maxRate);
    const y = plotTop + plotHeight - fraction * plotHeight;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function _speedGraphLegend() {
  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.gap = "16px";
  row.style.marginTop = "6px";

  for (const [color, label] of [
    [SPEED_GRAPH_COLOR_DOWNLOAD, "Téléchargement"],
    [SPEED_GRAPH_COLOR_UPLOAD, "Envoi"],
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

function openSpeedGraphDialog(infoHash, torrentName) {
  const contentEl = document.createElement("div");

  const canvas = document.createElement("canvas");
  canvas.width = 460;
  canvas.height = 220;
  contentEl.appendChild(canvas);
  contentEl.appendChild(_speedGraphLegend());

  const ctx = canvas.getContext("2d");

  const refresh = () => {
    window.bridge.speedGraph.getSpeedHistory(infoHash, (history) => {
      _drawSpeedGraph(ctx, canvas.width, canvas.height, history);
    });
  };
  refresh();
  const timer = setInterval(refresh, 1000);

  openModal(`Vitesse — ${torrentName}`, contentEl, () => clearInterval(timer));
}
