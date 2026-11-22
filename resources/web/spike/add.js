// Add/Analysis page wiring. Mirrors AddTorrentTab's exact behavior (see
// Phase 1+ research notes): drop/browse converge on selectTorrentFile(),
// Analyze tries the file source then the magnet source, Start requires two
// clicks for an unanalyzed magnet (server pushes a "pending" status back).

const LEVEL_LABEL_KEYS = {
  SAFE: "file_tree_risk.level_safe",
  LOW: "file_tree_risk.level_low",
  MEDIUM: "file_tree_risk.level_medium",
  HIGH: "file_tree_risk.level_high",
  CRITICAL: "file_tree_risk.level_critical",
};

function addLevelLabel(level) {
  const key = LEVEL_LABEL_KEYS[level];
  return key ? t(key) : level;
}

let addSelectedPath = null;
let addLastScan = null; // { fileRisks, threshold }
let addDefaultDestination = ""; // last default read from the bridge (addRefreshDefaultDestination): tells the field's untouched value from a chosen one
let addSuggestedDestination = ""; // last routing-rule prefill: the next scan may replace it, unlike a destination the user chose

// Intent-guided preset: purely a prefill convenience over existing mechanics
// (torrent_categories.py's free-text category, routing_rules.py's
// resolve_destination(), and the share-policy defaults ShareLimitService
// already reads from Settings) -- see bridge_add.py. Nothing here is
// validated or enforced; every prefilled field stays freely editable.
// "other" has no keyword list on purpose: no plausible category to guess,
// so picking it only surfaces the share-policy note, if any.
const ADD_INTENT_CATEGORY_GUESSES = {
  movie: { fallbackKey: "web.add.category_movie_fallback", keywords: ["film", "vidéo", "video", "série", "serie", "épisode", "episode"] },
  software: { fallbackKey: "web.add.category_software_fallback", keywords: ["logiciel", "app", "programme", "soft"] },
  document: { fallbackKey: "web.add.category_document_fallback", keywords: ["document", "doc", "livre", "ebook"] },
};

function addGuessCategory(intent, existingCategories) {
  const spec = ADD_INTENT_CATEGORY_GUESSES[intent];
  if (!spec) return ""; // "other" or unknown -- no invented mapping
  const existing = existingCategories.find((c) => spec.keywords.some((k) => c.toLowerCase().includes(k)));
  return existing || t(spec.fallbackKey);
}

function addApplyIntentPreset(intent) {
  const addBridge = window.bridge.add;
  addBridge.defaultSharePolicyNote((note) => {
    document.getElementById("addSharePolicyNote").textContent = note;
  });
  if (!intent) return;
  addBridge.listCategories((categories) => {
    const category = addGuessCategory(intent, categories);
    if (!category) return;
    document.getElementById("addCategoryInput").value = category;
    addBridge.resolveDestination(category, (dest) => {
      if (dest && dest !== addDefaultDestination) {
        document.getElementById("addDestInput").value = dest;
      }
    });
  });
}

function addRenderScan(scan) {
  addLastScan = scan;
  // Prefills the destination the same way a matching RSS auto-download
  // already does (rss_feed_service.py) -- but only while the field still
  // holds the default or the previous torrent's suggestion (so a torrent no
  // rule matches goes back to the default), never over something the user
  // typed or picked via the intent preset below.
  const destInput = document.getElementById("addDestInput");
  if (
    scan.suggestedDestination &&
    (destInput.value === addDefaultDestination || destInput.value === addSuggestedDestination)
  ) {
    destInput.value = scan.suggestedDestination;
    addSuggestedDestination = scan.suggestedDestination;
  }
  const list = document.getElementById("addScanList");
  list.replaceChildren();
  if (!scan.fileRisks.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = t("web.add.no_files_in_torrent");
    note.dataset.i18nKey = "web.add.no_files_in_torrent";
    list.appendChild(note);
    return;
  }
  scan.fileRisks.forEach((risk) => {
    const row = document.createElement("div");
    row.className = "scan-row";
    row.dataset.index = String(risk.index);

    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = risk.score < scan.threshold;
    check.className = "scan-check";
    row.appendChild(check);

    const path = document.createElement("span");
    path.className = "scan-path";
    path.textContent = risk.path; // safe: .textContent, not innerHTML -- path comes from torrent metadata
    path.title = risk.path;
    row.appendChild(path);

    const size = document.createElement("span");
    size.className = "scan-size";
    size.textContent = formatSize(risk.size);
    row.appendChild(size);

    const level = document.createElement("span");
    level.className = `risk-badge risk-${risk.level.toLowerCase()}`;
    level.textContent = addLevelLabel(risk.level);
    if (LEVEL_LABEL_KEYS[risk.level]) level.dataset.i18nKey = LEVEL_LABEL_KEYS[risk.level];
    row.appendChild(level);

    const reasons = document.createElement("span");
    reasons.className = "scan-reasons";
    reasons.textContent = risk.reasons.join("; ");
    reasons.title = reasons.textContent;
    row.appendChild(reasons);

    list.appendChild(row);
  });
}

function addExcludedIndices() {
  const excluded = [];
  document.querySelectorAll("#addScanList .scan-row").forEach((row) => {
    const check = row.querySelector(".scan-check");
    if (!check.checked) excluded.push(parseInt(row.dataset.index, 10));
  });
  return excluded;
}

function addClearScanList() {
  const list = document.getElementById("addScanList");
  list.replaceChildren();
  const note = document.createElement("p");
  note.className = "empty-note";
  note.textContent = t("web.add.no_scan_yet");
  note.dataset.i18nKey = "web.add.no_scan_yet";
  list.appendChild(note);
}

// The default folder can change in Profile at any time: re-read it, and move
// the field along while it still holds the old one.
function addRefreshDefaultDestination() {
  window.bridge.add.defaultDestination((dest) => {
    const destInput = document.getElementById("addDestInput");
    if (destInput.value === addDefaultDestination) destInput.value = dest;
    addDefaultDestination = dest;
  });
}

function addResetForm() {
  addSelectedPath = null;
  document.getElementById("addSelectedFile").textContent = "";
  document.getElementById("addMagnetInput").value = "";
  document.getElementById("addDestInput").value = addDefaultDestination;
  addSuggestedDestination = "";
  addRefreshDefaultDestination();
  document.getElementById("addIntentSelect").value = "";
  document.getElementById("addCategoryInput").value = "";
  document.getElementById("addSharePolicyNote").textContent = "";
  addClearScanList();
  addLastScan = null;
}

// A magnet from elsewhere (a search result, the clipboard): the .torrent
// picked before must not stay on screen, nor be what Analyser picks again.
function addAnalyzeMagnet(uri) {
  addSelectedPath = null;
  document.getElementById("addSelectedFile").textContent = "";
  addClearScanList();
  addLastScan = null;
  window.bridge.add.analyzeMagnet(uri);
}

// Also used by search.js for a result's fetched .torrent.
function addLoadTorrentFile(path, label) {
  addSelectedPath = path;
  document.getElementById("addSelectedFile").textContent = label;
  window.bridge.add.selectTorrentFile(path);
}

async function addHandleDroppedFile(file) {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const base64 = btoa(bytesToBinaryString(bytes));
  window.bridge.add.saveDroppedTorrent(file.name, base64, (path) => addLoadTorrentFile(path, file.name));
}

function wireAddPage() {
  const addBridge = window.bridge.add;
  const dialogs = window.bridge.dialogs;

  addRefreshDefaultDestination();
  document.querySelector('.tab-btn[data-tab="add"]').addEventListener("click", addRefreshDefaultDestination);
  addBridge.defaultThreshold((threshold) => {
    document.getElementById("addThresholdInput").value = threshold;
  });
  addBridge.listCategories((categories) => {
    const datalist = document.getElementById("addCategoryList");
    datalist.replaceChildren();
    categories.forEach((c) => {
      const option = document.createElement("option");
      option.value = c;
      datalist.appendChild(option);
    });
  });

  document.getElementById("addIntentSelect").addEventListener("change", (e) => {
    addApplyIntentPreset(e.target.value);
  });

  document.getElementById("addBrowseBtn").addEventListener("click", () => {
    dialogs.browseTorrentFile((path) => {
      if (!path) return;
      addSelectedPath = path;
      document.getElementById("addSelectedFile").textContent = path.split(/[\\/]/).pop();
      addBridge.selectTorrentFile(path);
    });
  });

  document.getElementById("addDestBrowseBtn").addEventListener("click", () => {
    const current = document.getElementById("addDestInput").value;
    dialogs.browseFolder(current, (path) => {
      if (path) document.getElementById("addDestInput").value = path;
    });
  });

  document.getElementById("addAnalyzeBtn").addEventListener("click", () => {
    if (addSelectedPath) {
      addBridge.selectTorrentFile(addSelectedPath);
    } else {
      const magnet = document.getElementById("addMagnetInput").value.trim();
      if (magnet) addBridge.analyzeMagnet(magnet);
    }
  });

  document.getElementById("addThresholdInput").addEventListener("change", (e) => {
    addBridge.setThreshold(parseInt(e.target.value, 10) || 0);
  });

  document.getElementById("addCreateTorrentBtn").addEventListener("click", () => {
    openCreateTorrentDialog();
  });

  document.getElementById("addCheckAllBtn").addEventListener("click", () => {
    document.querySelectorAll("#addScanList .scan-check").forEach((c) => (c.checked = true));
  });
  document.getElementById("addUncheckAllBtn").addEventListener("click", () => {
    document.querySelectorAll("#addScanList .scan-check").forEach((c) => (c.checked = false));
  });

  document.getElementById("addStartBtn").addEventListener("click", () => {
    const dest = document.getElementById("addDestInput").value;
    const magnet = document.getElementById("addMagnetInput").value;
    const category = document.getElementById("addCategoryInput").value;
    addBridge.startTorrent(dest, magnet, category, addExcludedIndices(), (result) => {
      document.getElementById("addStatus").textContent = result.error || "";
    });
  });

  addBridge.scanReady.connect(addRenderScan);
  addBridge.statusChanged.connect((msg) => {
    document.getElementById("addStatus").textContent = msg;
  });
  addBridge.blockedByTheme.connect(() => {
    document.getElementById("addStatus").textContent = t("web.add.blocked_by_theme");
  });
  addBridge.started.connect(() => {
    document.getElementById("addStatus").textContent = t("web.add.torrent_added");
    addResetForm();
    switchToTab("downloads");
  });

  const dropZone = document.getElementById("addDropZone");
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const file = [...e.dataTransfer.files].find((f) => f.name.toLowerCase().endsWith(".torrent"));
    if (file) {
      document.getElementById("addSelectedFile").textContent = file.name;
      addHandleDroppedFile(file);
    }
  });
}
