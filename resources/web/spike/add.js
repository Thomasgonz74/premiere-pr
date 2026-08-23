// Add/Analysis page wiring. Mirrors AddTorrentTab's exact behavior (see
// Phase 1+ research notes): drop/browse converge on selectTorrentFile(),
// Analyze tries the file source then the magnet source, Start requires two
// clicks for an unanalyzed magnet (server pushes a "pending" status back).

const LEVEL_LABELS = { SAFE: "Sûr", LOW: "Faible", MEDIUM: "Moyen", HIGH: "Élevé", CRITICAL: "Critique" };

let addSelectedPath = null;
let addLastScan = null; // { fileRisks, threshold }

function addRenderScan(scan) {
  addLastScan = scan;
  const list = document.getElementById("addScanList");
  list.replaceChildren();
  if (!scan.fileRisks.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = "Aucun fichier dans ce torrent.";
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
    level.textContent = LEVEL_LABELS[risk.level] || risk.level;
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
  note.textContent = "Aucune analyse pour l’instant.";
  list.appendChild(note);
}

function addResetForm() {
  addSelectedPath = null;
  document.getElementById("addSelectedFile").textContent = "";
  document.getElementById("addMagnetInput").value = "";
  addClearScanList();
  addLastScan = null;
}

async function addHandleDroppedFile(file) {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  const base64 = btoa(binary);
  window.bridge.add.saveDroppedTorrent(file.name, base64, (path) => {
    addSelectedPath = path;
    document.getElementById("addSelectedFile").textContent = file.name;
    window.bridge.add.selectTorrentFile(path);
  });
}

function wireAddPage() {
  const addBridge = window.bridge.add;
  const dialogs = window.bridge.dialogs;

  addBridge.defaultDestination((dest) => {
    document.getElementById("addDestInput").value = dest;
  });
  addBridge.defaultThreshold((threshold) => {
    document.getElementById("addThresholdInput").value = threshold;
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
    addBridge.startTorrent(dest, magnet, addExcludedIndices(), (result) => {
      document.getElementById("addStatus").textContent = result.error || "";
    });
  });

  addBridge.scanReady.connect(addRenderScan);
  addBridge.statusChanged.connect((msg) => {
    document.getElementById("addStatus").textContent = msg;
  });
  addBridge.blockedByTheme.connect(() => {
    document.getElementById("addStatus").textContent = "Démarrage bloqué par le thème actif.";
  });
  addBridge.started.connect(() => {
    document.getElementById("addStatus").textContent = "Torrent ajouté.";
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
