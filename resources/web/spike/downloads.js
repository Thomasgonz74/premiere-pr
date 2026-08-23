// Downloads page: full parity with native DownloadsTab -- 9-column rows
// (name/progress/ETA/DL/UL/peers-seeds/state/category/action), health-color
// backgrounds, private-torrent badge, single/multi row selection (Ctrl/Shift
// click, matching QTableWidget's ExtendedSelection), a details panel for the
// single selected torrent (current tracker, pause/resume, queue up/down,
// sequential checkbox, full tracker editor), a complete context menu
// (single + multi selection), category assignment, magnet-URI copy, and
// confirm-before-remove (with an optional delete-files choice) everywhere a
// torrent can be removed. Ported field-for-field from downloads_tab.py.

const DOWNLOADS_STATE_LABELS = {
  QUEUED: "En attente",
  CHECKING_METADATA: "Récup. métadonnées...",
  AWAITING_ANALYSIS: "En attente d'analyse",
  DOWNLOADING: "Téléchargement",
  PAUSED: "En pause",
  SEEDING: "Partage (seed)",
  FINISHED: "Terminé",
  ERROR: "Erreur",
};

const downloadsRows = new Map(); // infoHash -> { el, tetris, record }
let downloadsLastClickedHash = null;
let downloadsDetailsTrackerEditorFor = null;

function downloadsRowOrder() {
  return [...document.querySelectorAll("#downloadsList .row")];
}

function downloadsSelectedHashes() {
  return downloadsRowOrder()
    .filter((r) => r.classList.contains("selected"))
    .map((r) => r.dataset.infoHash);
}

function downloadsClearSelection() {
  document.querySelectorAll("#downloadsList .row.selected").forEach((r) => r.classList.remove("selected"));
}

function downloadsEta(record) {
  // Mirrors downloads_tab.py's _eta_text() exactly.
  if (record.downloadRate > 0 && record.progress < 1.0) {
    const remainingBytes = record.totalSize * (1 - record.progress);
    return formatEta(remainingBytes / record.downloadRate);
  }
  return formatEta(null);
}

function downloadsEnsureRow(record) {
  let entry = downloadsRows.get(record.infoHash);
  if (entry) return entry;

  const list = document.getElementById("downloadsList");
  document.getElementById("emptyNote")?.remove();

  // Built via safe DOM methods, not innerHTML -- record.name comes from
  // .torrent metadata/magnet dn=, which is untrusted external input.
  const el = document.createElement("div");
  el.className = "row downloads-row";
  el.dataset.infoHash = record.infoHash;

  const nameEl = document.createElement("div");
  nameEl.className = "row-name";
  el.appendChild(nameEl);

  const canvas = document.createElement("canvas");
  canvas.className = "tetris";
  el.appendChild(canvas);

  const etaEl = document.createElement("div");
  etaEl.className = "row-eta";
  el.appendChild(etaEl);

  const downRateEl = document.createElement("div");
  downRateEl.className = "row-rate";
  el.appendChild(downRateEl);

  const upRateEl = document.createElement("div");
  upRateEl.className = "row-rate";
  el.appendChild(upRateEl);

  const peersEl = document.createElement("div");
  peersEl.className = "row-peers";
  el.appendChild(peersEl);

  const stateEl = document.createElement("div");
  stateEl.className = "row-state";
  el.appendChild(stateEl);

  const categoryEl = document.createElement("div");
  categoryEl.className = "row-category";
  el.appendChild(categoryEl);

  const actionsEl = document.createElement("div");
  actionsEl.className = "row-actions";
  const pauseResumeBtn = document.createElement("button");
  pauseResumeBtn.dataset.action = "pause-resume";
  const removeBtn = document.createElement("button");
  removeBtn.dataset.action = "remove";
  removeBtn.textContent = "✕";
  actionsEl.appendChild(pauseResumeBtn);
  actionsEl.appendChild(removeBtn);
  el.appendChild(actionsEl);

  list.appendChild(el);
  const tetris = registerTetrisCanvas(canvas);

  el.addEventListener("click", (event) => downloadsHandleRowClick(record.infoHash, event));
  el.addEventListener("contextmenu", (event) => downloadsHandleContextMenu(record.infoHash, event));

  pauseResumeBtn.addEventListener("click", () => {
    const current = downloadsRows.get(record.infoHash);
    if (!current) return;
    if (current.record.state === "PAUSED") {
      window.bridge.downloads.resumeTorrent(record.infoHash);
    } else {
      window.bridge.downloads.pauseTorrent(record.infoHash);
    }
  });
  removeBtn.addEventListener("click", () => {
    confirmAndRemove(
      () => window.bridge.downloads.removeTorrent(record.infoHash, false),
      () => window.bridge.downloads.removeTorrent(record.infoHash, true)
    );
  });

  entry = { el, tetris, record };
  downloadsRows.set(record.infoHash, entry);
  return entry;
}

function downloadsRenderRecord(record) {
  const entry = downloadsEnsureRow(record);
  entry.record = record;
  entry.el.dataset.lastState = record.state;
  entry.el.dataset.health = record.healthStatus || "";

  const nameEl = entry.el.querySelector(".row-name");
  const displayName = record.isPrivate ? `\u{1F512} ${record.name}` : record.name;
  nameEl.textContent = displayName; // safe: DOM property assignment, not HTML parsing
  nameEl.title = record.isPrivate
    ? `${record.name}\n\nTorrent privé : DHT, PEX et LSD restent désactivés pour ce torrent, quels que soient vos réglages de confidentialité globaux.`
    : record.name;

  entry.el.querySelector(".row-eta").textContent = downloadsEta(record);
  const rateEls = entry.el.querySelectorAll(".row-rate");
  rateEls[0].textContent = `↓ ${formatRate(record.downloadRate)}`;
  rateEls[1].textContent = `↑ ${formatRate(record.uploadRate)}`;
  entry.el.querySelector(".row-peers").textContent = `${record.numPeers} (${record.numSeeds} seeds)`;
  entry.el.querySelector(".row-state").textContent = DOWNLOADS_STATE_LABELS[record.state] || record.state;
  entry.el.querySelector(".row-category").textContent = record.category || "";
  entry.el.querySelector('[data-action="pause-resume"]').textContent = record.state === "PAUSED" ? "▶" : "⏸";
  entry.tetris.setProgress(record.progress);

  downloadsUpdateDetailsPanel();
  downloadsApplyFilter();
}

function downloadsRemoveRecord(infoHash) {
  const entry = downloadsRows.get(infoHash);
  if (!entry) return;
  entry.el.remove();
  downloadsRows.delete(infoHash);
  if (downloadsRows.size === 0) {
    const list = document.getElementById("downloadsList");
    const note = document.createElement("p");
    note.className = "empty-note";
    note.id = "emptyNote";
    note.textContent = "Aucun torrent actif — ajoutez-en un depuis l'onglet Ajouter pour le voir apparaître ici en direct.";
    list.appendChild(note);
  }
  downloadsUpdateDetailsPanel();
}

// -------------------------------------------------------------- selection

function downloadsHandleRowClick(infoHash, event) {
  const all = downloadsRowOrder();
  const el = downloadsRows.get(infoHash)?.el;
  if (!el) return;

  if (event.shiftKey && downloadsLastClickedHash) {
    const fromIdx = all.findIndex((r) => r.dataset.infoHash === downloadsLastClickedHash);
    const toIdx = all.findIndex((r) => r.dataset.infoHash === infoHash);
    if (fromIdx !== -1 && toIdx !== -1) {
      downloadsClearSelection();
      const [start, end] = fromIdx < toIdx ? [fromIdx, toIdx] : [toIdx, fromIdx];
      for (let i = start; i <= end; i++) all[i].classList.add("selected");
    }
  } else if (event.ctrlKey || event.metaKey) {
    el.classList.toggle("selected");
    downloadsLastClickedHash = infoHash;
  } else {
    downloadsClearSelection();
    el.classList.add("selected");
    downloadsLastClickedHash = infoHash;
  }
  downloadsUpdateDetailsPanel();
}

// ---------------------------------------------------------- details panel

function downloadsUpdateDetailsPanel() {
  const panel = document.getElementById("downloadsDetails");
  const selected = downloadsSelectedHashes();
  const entry = selected.length === 1 ? downloadsRows.get(selected[0]) : null;

  if (!entry) {
    panel.style.display = "none";
    downloadsDetailsTrackerEditorFor = null;
    return;
  }

  panel.style.display = "flex";
  const infoHash = selected[0];
  const record = entry.record;
  document.getElementById("downloadsDetailsTracker").textContent = `Tracker actuel : ${record.currentTracker || "—"}`;
  const queueText = record.queuePosition >= 0 ? `position ${record.queuePosition + 1}` : "actif (pas en attente)";
  document.getElementById("downloadsDetailsQueue").textContent = `File d'attente : ${queueText}`;
  document.getElementById("downloadsDetailsSequential").checked = record.sequentialDownload;

  // Only rebuild the tracker editor when the selected torrent actually
  // changes -- rebuilding on every status tick would blow away whatever the
  // user is mid-typing in its "add tracker" input.
  if (downloadsDetailsTrackerEditorFor !== infoHash) {
    downloadsDetailsTrackerEditorFor = infoHash;
    renderTrackerEditor(document.getElementById("downloadsDetailsTrackerEditor"), infoHash);
  }
}

// ----------------------------------------------------------------- filter

function downloadsApplyFilter() {
  const query = document.getElementById("downloadsSearchInput").value.trim().toLowerCase();
  downloadsRows.forEach((entry) => {
    const name = (entry.record.name || "").toLowerCase();
    entry.el.style.display = !query || name.includes(query) ? "" : "none";
  });
}

// ------------------------------------------------------------ context menu

function downloadsHandleContextMenu(infoHash, event) {
  event.preventDefault();
  event.stopPropagation();

  let selected = downloadsSelectedHashes();
  if (!(selected.includes(infoHash) && selected.length > 1)) {
    downloadsClearSelection();
    downloadsRows.get(infoHash)?.el.classList.add("selected");
    downloadsLastClickedHash = infoHash;
    downloadsUpdateDetailsPanel();
    selected = [infoHash];
  }

  if (selected.length > 1) {
    showContextMenu(event.clientX, event.clientY, downloadsBuildMultiMenu(selected));
  } else {
    showContextMenu(event.clientX, event.clientY, downloadsBuildSingleMenu(infoHash));
  }
}

function downloadsBuildSingleMenu(infoHash) {
  const entry = downloadsRows.get(infoHash);
  const record = entry ? entry.record : null;
  const name = record ? record.name : infoHash;
  const items = [];

  if (record && record.state === "PAUSED") {
    items.push({ label: "Reprendre", onClick: () => window.bridge.downloads.resumeTorrent(infoHash) });
  } else {
    items.push({ label: "Pause", onClick: () => window.bridge.downloads.pauseTorrent(infoHash) });
  }
  items.push({ label: "Revérifier", onClick: () => window.bridge.downloads.recheckTorrent(infoHash) });
  items.push({
    label: "Déplacer les fichiers…",
    onClick: () => {
      window.bridge.dialogs.browseFolder("", (path) => {
        if (path) window.bridge.downloads.moveStorage(infoHash, path);
      });
    },
  });
  items.push({ separator: true });
  items.push({
    label: "Assigner une catégorie…",
    onClick: () => downloadsOpenCategoryDialog(infoHash, record ? record.category : ""),
  });
  items.push({
    label: "Copier le lien magnet",
    onClick: () => {
      window.bridge.downloads.getMagnetUri(infoHash, (uri) => {
        if (uri) {
          navigator.clipboard.writeText(uri);
        } else {
          alertModal(
            "Lien magnet indisponible",
            "Le lien magnet n'est pas encore disponible pour ce torrent : les métadonnées n'ont pas encore été reçues. Réessayez une fois le torrent analysé."
          );
        }
      });
    },
  });
  items.push({ label: "Modifier les fichiers…", onClick: () => openFilePriorityDialog(infoHash, name) });
  items.push({ label: "Voir les pairs", onClick: () => openPeerListDialog(infoHash, name) });
  items.push({ label: "Voir le graphique de vitesse", onClick: () => openSpeedGraphDialog(infoHash, name) });
  items.push({ separator: true });
  items.push({
    label: "Retirer",
    onClick: () =>
      confirmAndRemove(
        () => window.bridge.downloads.removeTorrent(infoHash, false),
        () => window.bridge.downloads.removeTorrent(infoHash, true)
      ),
  });
  return items;
}

function downloadsBuildMultiMenu(hashes) {
  return [
    {
      label: "Mettre en pause la sélection",
      onClick: () => hashes.forEach((h) => window.bridge.downloads.pauseTorrent(h)),
    },
    {
      label: "Reprendre la sélection",
      onClick: () => hashes.forEach((h) => window.bridge.downloads.resumeTorrent(h)),
    },
    { separator: true },
    {
      label: "Retirer la sélection",
      onClick: () =>
        confirmAndRemove(
          () => hashes.forEach((h) => window.bridge.downloads.removeTorrent(h, false)),
          () => hashes.forEach((h) => window.bridge.downloads.removeTorrent(h, true))
        ),
    },
  ];
}

function downloadsOpenCategoryDialog(infoHash, currentCategory) {
  window.bridge.downloads.listCategories((categories) => {
    const content = document.createElement("div");
    content.className = "form-grid";

    const label = document.createElement("label");
    label.className = "field-label";
    label.textContent = "Catégorie :";
    content.appendChild(label);

    const input = document.createElement("input");
    input.type = "text";
    input.value = currentCategory || "";
    input.setAttribute("list", "downloadsCategoryList");
    content.appendChild(input);

    const datalist = document.createElement("datalist");
    datalist.id = "downloadsCategoryList";
    categories.forEach((c) => {
      const option = document.createElement("option");
      option.value = c;
      datalist.appendChild(option);
    });
    content.appendChild(datalist);

    const buttonRow = document.createElement("div");
    buttonRow.className = "modal-close-row";
    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Enregistrer";
    saveBtn.addEventListener("click", () => {
      window.bridge.downloads.setCategory(infoHash, input.value.trim());
      closeModal();
    });
    buttonRow.appendChild(saveBtn);
    const cancelBtn = document.createElement("button");
    cancelBtn.textContent = "Annuler";
    cancelBtn.addEventListener("click", () => closeModal());
    buttonRow.appendChild(cancelBtn);
    content.appendChild(buttonRow);

    openModal("Assigner une catégorie", content);
  });
}

// -------------------------------------------------------------------- wire

function wireDownloadsPage() {
  const bridge = window.bridge.downloads;
  bridge.recordUpdated.connect(downloadsRenderRecord);
  bridge.recordRemoved.connect(downloadsRemoveRecord);
  bridge.listTorrents((initial) => initial.forEach(downloadsRenderRecord));

  document.getElementById("downloadsSearchInput").addEventListener("input", downloadsApplyFilter);

  document.getElementById("downloadsDetailsPauseBtn").addEventListener("click", () => {
    const sel = downloadsSelectedHashes();
    if (sel.length === 1) window.bridge.downloads.pauseTorrent(sel[0]);
  });
  document.getElementById("downloadsDetailsResumeBtn").addEventListener("click", () => {
    const sel = downloadsSelectedHashes();
    if (sel.length === 1) window.bridge.downloads.resumeTorrent(sel[0]);
  });
  document.getElementById("downloadsDetailsQueueUpBtn").addEventListener("click", () => {
    const sel = downloadsSelectedHashes();
    if (sel.length === 1) window.bridge.downloads.moveQueueUp(sel[0]);
  });
  document.getElementById("downloadsDetailsQueueDownBtn").addEventListener("click", () => {
    const sel = downloadsSelectedHashes();
    if (sel.length === 1) window.bridge.downloads.moveQueueDown(sel[0]);
  });
  document.getElementById("downloadsDetailsSequential").addEventListener("change", (event) => {
    const sel = downloadsSelectedHashes();
    if (sel.length === 1) window.bridge.downloads.setSequentialDownload(sel[0], event.target.checked);
  });

  downloadsUpdateDetailsPanel(); // starts hidden -- nothing selected yet
}
