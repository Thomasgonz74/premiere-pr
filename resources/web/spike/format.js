// Shared formatting helpers -- used by app.js (Downloads), add.js, share.js.
// Mirrors the native app's human_rate/human_size/human_eta (utils/format.py)
// closely enough for this spike; not a byte-for-byte port.

function formatRate(bytesPerSec) {
  if (bytesPerSec < 1024) return `${bytesPerSec} o/s`;
  if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} Ko/s`;
  return `${(bytesPerSec / 1024 / 1024).toFixed(1)} Mo/s`;
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} Mo`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} Go`;
}

function formatEta(seconds) {
  // Mirrors utils/formatting.py's human_eta() exactly (distinct spacing/
  // unit convention from formatDuration -- "1h 02m" vs "1h02").
  if (seconds === null || seconds === undefined || seconds < 0 || seconds === Infinity) return "—";
  seconds = Math.floor(seconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes > 0) return `${minutes}m ${String(secs).padStart(2, "0")}s`;
  return `${secs}s`;
}

// Shared by add.js/share.js's dropped-file handlers: converts a Uint8Array
// to a binary string for btoa(), in chunks rather than one
// String.fromCharCode() call per byte -- same output, far fewer function
// calls/concatenations for a large .torrent's metadata. Still fully
// synchronous (no yield between chunks), just much faster than per-byte.
function bytesToBinaryString(bytes) {
  const CHUNK = 0x8000; // well under every engine's Function.apply argument-count limit
  let binary = "";
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return binary;
}

function formatDuration(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h${String(m).padStart(2, "0")}`;
  if (m > 0) return `${m}m${String(s).padStart(2, "0")}`;
  return `${s}s`;
}
