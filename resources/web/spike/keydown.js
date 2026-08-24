// Global keyboard shortcuts, mirrors MainWindow's native QShortcuts
// (Ctrl+O, Ctrl+Tab, Delete, Space). Implemented purely in JS rather than as
// native QShortcut on SpikeWindow -- this session already found that native
// mouse events never reach the window once QWebEngineView content has focus
// (window drag needed a JS->Python bridge call instead), so a top-level
// QShortcut would carry the same risk of never firing while the embedded
// page has keyboard focus. A JS keydown listener is the reliable pattern
// here, consistent with everything else in this port.

function shortcutNextTab() {
  const buttons = [...document.querySelectorAll(".tab-btn")];
  const current = buttons.findIndex((b) => b.classList.contains("active"));
  buttons[(current + 1) % buttons.length].click();
}

function _selectedDownloadInfoHash() {
  // Mirrors MainWindow._selected_downloads_info_hash(): only meaningful
  // while the Downloads tab is the one on screen, and only when exactly one
  // row is selected (a multi-selection has no single shortcut target,
  // matching native -- bulk operations go through the context menu instead).
  if (!document.getElementById("page-downloads").classList.contains("active")) return null;
  const selected = downloadsSelectedHashes();
  return selected.length === 1 ? selected[0] : null;
}

function shortcutRemoveSelectedDownload() {
  const infoHash = _selectedDownloadInfoHash();
  if (!infoHash) return;
  confirmAndRemove(
    () => window.bridge.downloads.removeTorrent(infoHash, false),
    () => window.bridge.downloads.removeTorrent(infoHash, true),
    downloadsRemovalImpact([infoHash])
  );
}

function shortcutPauseResumeSelectedDownload() {
  const infoHash = _selectedDownloadInfoHash();
  if (!infoHash) return;
  const record = downloadsRows.get(infoHash)?.record;
  if (record && record.state === "PAUSED") {
    window.bridge.downloads.resumeTorrent(infoHash);
  } else {
    window.bridge.downloads.pauseTorrent(infoHash);
  }
}

document.addEventListener("keydown", (event) => {
  // Text-entry fields handle their own keys (typing "o" or " " in a field
  // shouldn't trigger a global shortcut) -- matches QShortcut naturally
  // deferring to a focused QLineEdit.
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;

  if (event.ctrlKey && event.key.toLowerCase() === "o") {
    event.preventDefault();
    switchToTab("add");
    document.getElementById("addBrowseBtn").click();
  } else if (event.ctrlKey && event.key === "Tab") {
    event.preventDefault();
    shortcutNextTab();
  } else if (event.key === "Delete") {
    shortcutRemoveSelectedDownload();
  } else if (event.key === " ") {
    event.preventDefault();
    shortcutPauseResumeSelectedDownload();
  }
});
