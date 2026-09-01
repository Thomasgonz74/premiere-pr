// Share page wiring. Mirrors ShareTab: row membership comes from the
// server's tracked_info_hashes() (see bridge_share.py), not from a client
// side filter -- the bridge only ever pushes rows for tracked torrents.

const SHARE_STATE_LABELS = {
  QUEUED: "En file",
  CHECKING_METADATA: "Vérification métadonnées",
  AWAITING_ANALYSIS: "En attente d'analyse",
  DOWNLOADING: "Téléchargement",
  PAUSED: "En pause",
  SEEDING: "Partage",
  FINISHED: "Terminé",
  ERROR: "Erreur",
};
const REASON_LABELS = { time: "Limite de temps atteinte", data: "Limite de données atteinte", ratio: "Ratio atteint" };

const shareRows = new Map(); // infoHash -> el
let shareSelectedPath = null;

function shareStateText(record) {
  if (record.reached) return REASON_LABELS[record.reachedReason] || "Limite atteinte";
  return SHARE_STATE_LABELS[record.state] || record.state;
}

function shareEnsureRow(record) {
  let el = shareRows.get(record.infoHash);
  if (el) return el;

  document.getElementById("shareEmptyNote")?.remove();

  el = document.createElement("div");
  el.className = "row share-row";

  const nameEl = document.createElement("div");
  nameEl.className = "row-name";
  el.appendChild(nameEl);

  const rateEl = document.createElement("div");
  rateEl.className = "row-rate";
  el.appendChild(rateEl);

  const dataEl = document.createElement("div");
  dataEl.className = "row-rate";
  el.appendChild(dataEl);

  const timeEl = document.createElement("div");
  timeEl.className = "row-rate";
  el.appendChild(timeEl);

  const stateEl = document.createElement("div");
  stateEl.className = "row-state";
  el.appendChild(stateEl);

  const actionsEl = document.createElement("div");
  actionsEl.className = "row-actions";
  const pauseBtn = document.createElement("button");
  pauseBtn.dataset.action = "pause-resume";
  const removeBtn = document.createElement("button");
  removeBtn.dataset.action = "remove";
  removeBtn.textContent = "✕";
  actionsEl.appendChild(pauseBtn);
  actionsEl.appendChild(removeBtn);
  el.appendChild(actionsEl);

  document.getElementById("shareList").appendChild(el);

  pauseBtn.addEventListener("click", () => {
    const current = shareRows.get(record.infoHash);
    if (current && current.dataset.lastState === "PAUSED") {
      window.bridge.share.resumeTorrent(record.infoHash);
    } else {
      window.bridge.share.pauseTorrent(record.infoHash);
    }
  });
  removeBtn.addEventListener("click", () => {
    window.bridge.share.removeTorrent(record.infoHash, false);
  });

  el.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const infoHash = record.infoHash;
    const name = el.querySelector(".row-name").textContent;
    showContextMenu(event.clientX, event.clientY, [
      { label: "Voir les pairs", onClick: () => openPeerListDialog(infoHash, name) },
      { label: "Graphique de vitesse", onClick: () => openSpeedGraphDialog(infoHash, name) },
      { label: "Modifier les fichiers…", onClick: () => openFilePriorityDialog(infoHash, name) },
      { separator: true },
      { label: "Revérifier", onClick: () => window.bridge.share.recheckTorrent(infoHash) },
      {
        label: "Déplacer les données…",
        onClick: () => {
          window.bridge.dialogs.browseFolder("", (path) => {
            if (path) window.bridge.share.moveStorage(infoHash, path);
          });
        },
      },
      { separator: true },
      { label: "Supprimer", onClick: () => window.bridge.share.removeTorrent(infoHash, false) },
    ]);
  });

  // Cached as plain properties on the element itself (rather than switching
  // shareRows to store a wrapper object) so the 3 other places that read
  // shareRows.get(infoHash) as the raw row element (.dataset.lastState in
  // the pause handler above, .remove() in shareRemoveRow, and the search
  // listener's forEach) keep working unchanged.
  el._nameEl = nameEl;
  el._rateEl = rateEl;
  el._dataEl = dataEl;
  el._timeEl = timeEl;
  el._stateEl = stateEl;
  el._pauseBtn = pauseBtn;

  shareRows.set(record.infoHash, el);
  return el;
}

function shareRenderRow(record) {
  const el = shareEnsureRow(record);
  el.dataset.lastState = record.state;
  el._nameEl.textContent = record.name;
  el._nameEl.title = record.name;
  el._rateEl.textContent = `↑ ${formatRate(record.uploadRate)}`;
  el._dataEl.textContent =
    record.dataLimitBytes != null
      ? `${formatSize(record.uploadedBytes)} / ${formatSize(record.dataLimitBytes)}`
      : formatSize(record.uploadedBytes);
  el._timeEl.textContent =
    record.timeLimitSeconds != null
      ? `${formatDuration(record.elapsedSeconds)} / ${formatDuration(record.timeLimitSeconds)}`
      : formatDuration(record.elapsedSeconds);
  el._stateEl.textContent = shareStateText(record);
  el._pauseBtn.textContent = record.state === "PAUSED" ? "▶" : "⏸";
}

function shareRemoveRow(infoHash) {
  const el = shareRows.get(infoHash);
  if (!el) return;
  el.remove();
  shareRows.delete(infoHash);
  if (shareRows.size === 0) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.id = "shareEmptyNote";
    note.textContent = "Aucun torrent partagé — ajoutez-en un ci-dessus pour le voir apparaître ici en direct.";
    document.getElementById("shareList").appendChild(note);
  }
}

async function shareHandleDroppedFile(file) {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const base64 = btoa(bytesToBinaryString(bytes));
  window.bridge.share.saveDroppedTorrent(file.name, base64, (path) => {
    shareSelectedPath = path;
    document.getElementById("shareSelectedFile").textContent = file.name;
    window.bridge.share.selectTorrentFile(path);
  });
}

function shareResetForm() {
  shareSelectedPath = null;
  document.getElementById("shareSelectedFile").textContent = "";
  document.getElementById("shareMagnetInput").value = "";
  document.getElementById("shareTimeLimitInput").value = 0;
  document.getElementById("shareDataLimitInput").value = 0;
  document.getElementById("shareRatioLimitInput").value = 0;
}

function wireSharePage() {
  const shareBridge = window.bridge.share;
  const dialogs = window.bridge.dialogs;

  shareBridge.defaultDataDir((dir) => {
    document.getElementById("shareDataDirInput").value = dir;
  });

  document.getElementById("shareBrowseBtn").addEventListener("click", () => {
    dialogs.browseTorrentFile((path) => {
      if (!path) return;
      shareSelectedPath = path;
      document.getElementById("shareSelectedFile").textContent = path.split(/[\\/]/).pop();
      shareBridge.selectTorrentFile(path);
    });
  });

  document.getElementById("shareDataDirBrowseBtn").addEventListener("click", () => {
    const current = document.getElementById("shareDataDirInput").value;
    dialogs.browseFolder(current, (path) => {
      if (path) document.getElementById("shareDataDirInput").value = path;
    });
  });

  document.getElementById("shareStartBtn").addEventListener("click", () => {
    const dataDir = document.getElementById("shareDataDirInput").value;
    const magnet = document.getElementById("shareMagnetInput").value;
    const timeLimit = parseInt(document.getElementById("shareTimeLimitInput").value, 10) || 0;
    const dataLimit = parseInt(document.getElementById("shareDataLimitInput").value, 10) || 0;
    const ratioLimit = parseFloat(document.getElementById("shareRatioLimitInput").value) || 0;
    shareBridge.startShare(dataDir, magnet, timeLimit, dataLimit, ratioLimit, (result) => {
      document.getElementById("shareStatus").textContent = result.error || "";
    });
  });

  shareBridge.started.connect(() => {
    document.getElementById("shareStatus").textContent = "Partage démarré.";
    shareResetForm();
  });
  shareBridge.recordUpdated.connect(shareRenderRow);
  shareBridge.recordRemoved.connect(shareRemoveRow);
  shareBridge.listTorrents((initial) => initial.forEach(shareRenderRow));

  document.getElementById("shareSearchInput").addEventListener("input", (e) => {
    const needle = e.target.value.toLowerCase();
    shareRows.forEach((el) => {
      const name = el.querySelector(".row-name").textContent.toLowerCase();
      el.style.display = name.includes(needle) ? "" : "none";
    });
  });

  const dropZone = document.getElementById("shareDropZone");
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
      document.getElementById("shareSelectedFile").textContent = file.name;
      shareHandleDroppedFile(file);
    }
  });
}
