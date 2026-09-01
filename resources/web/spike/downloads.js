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
let downloadsDetailsAllocatedFor = null;
let downloadsDetailsSlownessFor = null;
let downloadsDetailsDeadlineFor = null;
// infoHash currently shown in the details panel, or null -- lets
// downloadsRenderRecord() (called once per active torrent, every ~300ms
// tick) skip rebuilding the panel entirely for torrents that aren't the one
// currently displayed.
let downloadsDetailsVisibleFor = null;

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

// Builds the removal-impact preview passed to confirmAndRemove() -- looked
// up fresh from downloadsRows (not captured earlier), and from data already
// held client-side (record.totalSize/numSeeds/numPeers/state), so this never
// costs a bridge round-trip. Per-file counts would need an async
// bridge.filePriority.getFiles() call (metadata not always loaded yet); that
// round-trip is deliberately skipped here to avoid a visible delay before
// the confirmation dialog appears -- see modal.js's confirmAndRemove doc.
function downloadsRemovalImpact(hashes) {
  const records = hashes.map((h) => downloadsRows.get(h)?.record).filter(Boolean);
  const totalSize = records.reduce((sum, r) => sum + (r.totalSize || 0), 0);
  const impact = { count: hashes.length, totalSize };
  if (records.length === 1) {
    impact.numSeeds = records[0].numSeeds;
    impact.numPeers = records[0].numPeers;
    impact.stateLabel = DOWNLOADS_STATE_LABELS[records[0].state] || records[0].state;
  }
  return impact;
}

function downloadsEta(record) {
  // Mirrors downloads_tab.py's _eta_text() exactly.
  if (record.downloadRate > 0 && record.progress < 1.0) {
    const remainingBytes = record.totalSize * (1 - record.progress);
    return formatEta(remainingBytes / record.downloadRate);
  }
  return formatEta(null);
}

// ------------------------------------------------------------- deadline

// epoch seconds -> the local "YYYY-MM-DDTHH:mm" string <input
// type="datetime-local"> expects. Not toISOString() (that's UTC) -- built
// from the local getters so it round-trips through new Date(value) (which
// parses a timezone-less datetime-local string as local time) back to the
// same epoch second.
function downloadsEpochToDatetimeLocal(epochSeconds) {
  const d = new Date(epochSeconds * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function downloadsDeadlineRemainingText(record) {
  if (!record.deadline) return "Aucune échéance définie.";
  const remaining = record.deadline - Date.now() / 1000;
  if (remaining <= 0) return "Échéance dépassée !";
  return `Temps restant avant l'échéance : ${formatEta(remaining)}`;
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

  // Name column holds two children (identicon + name text) but stays a
  // single grid item -- .downloads-row's 9-column grid must keep matching
  // the 9-column header, so the identicon nests inside here rather than
  // becoming its own top-level grid child.
  const nameCell = document.createElement("div");
  nameCell.className = "row-name-cell";
  el.appendChild(nameCell);

  // Pin toggle: unlike the locked/private glyphs (plain text prefixes on
  // the name, below), this one is interactive -- a small always-present
  // button so pinning doesn't require opening the context menu.
  const pinBtn = document.createElement("button");
  pinBtn.type = "button";
  pinBtn.className = "row-pin-btn";
  pinBtn.textContent = "\u{1F4CC}"; // 📌
  nameCell.appendChild(pinBtn);
  pinBtn.addEventListener("click", (event) => {
    event.stopPropagation(); // don't trigger row selection
    const current = downloadsRows.get(record.infoHash);
    if (!current) return;
    if (current.record.pinned) {
      window.bridge.downloads.unpinTorrent(record.infoHash);
    } else {
      window.bridge.downloads.pinTorrent(record.infoHash);
    }
  });

  const identiconEl = document.createElement("canvas");
  identiconEl.className = "identicon";
  identiconEl.width = 20;
  identiconEl.height = 20;
  nameCell.appendChild(identiconEl);
  drawIdenticon(identiconEl, record.infoHash); // fixed per torrent, drawn once

  const nameEl = document.createElement("div");
  nameEl.className = "row-name";
  nameCell.appendChild(nameEl);

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
    const hash = record.infoHash;
    confirmAndRemove(
      () => window.bridge.downloads.removeTorrent(hash, false),
      () => window.bridge.downloads.removeTorrent(hash, true),
      downloadsRemovalImpact([hash])
    );
  });

  entry = {
    el,
    tetris,
    record,
    pinBtn,
    nameEl,
    etaEl,
    downRateEl,
    upRateEl,
    peersEl,
    stateEl,
    categoryEl,
    pauseResumeBtn,
  };
  downloadsRows.set(record.infoHash, entry);
  return entry;
}

// Pinned rows always sort before unpinned ones, in whatever order they were
// pinned. Rather than re-sorting the whole table on every status tick, this
// only moves a row the moment its pinned flag actually flips -- everything
// else keeps its current DOM position (see downloadsRenderRecord below).
function downloadsPlaceRow(el, pinned) {
  const list = document.getElementById("downloadsList");
  el.classList.toggle("pinned", pinned);
  if (pinned) {
    const firstUnpinned = list.querySelector(".row:not(.pinned)");
    list.insertBefore(el, firstUnpinned || null);
  } else {
    list.appendChild(el); // moves to the end, after all still-pinned rows
  }
}

function downloadsRenderRecord(record) {
  const wasPinned = downloadsRows.get(record.infoHash)?.record.pinned ?? false;
  const entry = downloadsEnsureRow(record);
  entry.record = record;
  entry.el.dataset.lastState = record.state;
  entry.el.dataset.health = record.healthStatus || "";
  if (!!record.pinned !== wasPinned) {
    downloadsPlaceRow(entry.el, !!record.pinned);
  }
  const pinBtn = entry.pinBtn;
  pinBtn.classList.toggle("active", !!record.pinned);
  pinBtn.title = record.pinned ? "Désépingler" : "Épingler en tête de liste";

  const nameEl = entry.nameEl;
  // Two distinct glyphs so a torrent that's both private and archived
  // doesn't read as a single doubled-up padlock: \u{1F510} (locked+key) for
  // the archive lock, \u{1F512} (plain padlock) for is_private, unchanged.
  const icons = [];
  if (record.locked) icons.push("\u{1F510}");
  if (record.isPrivate) icons.push("\u{1F512}");
  const displayName = icons.length ? `${icons.join(" ")} ${record.name}` : record.name;
  nameEl.textContent = displayName; // safe: DOM property assignment, not HTML parsing
  const tooltipParts = [record.name];
  if (record.locked) {
    tooltipParts.push(
      "Archivé (lecture seule) : les fichiers de ce torrent sont verrouillés en écriture sur le disque."
    );
  }
  if (record.isPrivate) {
    tooltipParts.push(
      "Torrent privé : DHT, PEX et LSD restent désactivés pour ce torrent, quels que soient vos réglages de confidentialité globaux."
    );
  }
  nameEl.title = tooltipParts.length > 1 ? tooltipParts.join("\n\n") : record.name;

  entry.etaEl.textContent = downloadsEta(record);
  entry.downRateEl.textContent = `↓ ${formatRate(record.downloadRate)}`;
  entry.upRateEl.textContent = `↑ ${formatRate(record.uploadRate)}`;
  entry.peersEl.textContent = `${record.numPeers} (${record.numSeeds} seeds)`;
  entry.stateEl.textContent = DOWNLOADS_STATE_LABELS[record.state] || record.state;
  entry.categoryEl.textContent = record.category || "";
  entry.pauseResumeBtn.textContent = record.state === "PAUSED" ? "▶" : "⏸";
  entry.tetris.setProgress(record.progress);

  // Only the torrent currently shown in the details panel needs it rebuilt;
  // direct callers (row click, context menu, action buttons) still call
  // downloadsUpdateDetailsPanel() unconditionally and keep
  // downloadsDetailsVisibleFor current on every selection change.
  if (record.infoHash === downloadsDetailsVisibleFor) {
    downloadsUpdateDetailsPanel();
  }
  downloadsSetRowVisibility(entry, downloadsCurrentFilterQuery());
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
    downloadsDetailsVisibleFor = null;
    panel.style.display = "none";
    downloadsDetailsTrackerEditorFor = null;
    downloadsDetailsAllocatedFor = null;
    downloadsDetailsSlownessFor = null;
    downloadsDetailsDeadlineFor = null;
    return;
  }

  panel.style.display = "flex";
  const infoHash = selected[0];
  downloadsDetailsVisibleFor = infoHash;
  const record = entry.record;
  document.getElementById("downloadsDetailsTracker").textContent = `Tracker actuel : ${record.currentTracker || "—"}`;

  // Stale "why is it slow" result from a previously-selected torrent would
  // be misleading left on screen -- clear it the moment selection changes.
  // Not re-fetched automatically on the new torrent: on-demand only, per
  // the button below.
  if (downloadsDetailsSlownessFor !== infoHash) {
    downloadsDetailsSlownessFor = infoHash;
    const slownessEl = document.getElementById("downloadsDetailsSlowness");
    slownessEl.textContent = "";
    slownessEl.style.display = "none";
  }
  // A real disk syscall per file on the Python side -- fetched on demand
  // each time the selected torrent changes, not part of the constant
  // status-tick push (see bridge_downloads.py::getAllocatedSize).
  if (downloadsDetailsAllocatedFor !== infoHash) {
    downloadsDetailsAllocatedFor = infoHash;
    const allocatedEl = document.getElementById("downloadsDetailsAllocated");
    allocatedEl.textContent = "Espace occupé sur le disque : calcul...";
    window.bridge.downloads.getAllocatedSize(infoHash, (allocatedBytes) => {
      if (downloadsDetailsAllocatedFor !== infoHash) return; // selection changed while awaiting the reply
      const logicalText = formatSize(record.totalSize);
      const allocatedText = formatSize(allocatedBytes);
      allocatedEl.textContent = allocatedBytes === record.totalSize
        ? `Espace occupé sur le disque : ${allocatedText} (identique à la taille annoncée)`
        : `Espace occupé sur le disque : ${allocatedText} (taille annoncée : ${logicalText})`;
    });
  }

  const queueText = record.queuePosition >= 0 ? `position ${record.queuePosition + 1}` : "actif (pas en attente)";
  document.getElementById("downloadsDetailsQueue").textContent = `File d'attente : ${queueText}`;
  document.getElementById("downloadsDetailsSequential").checked = record.sequentialDownload;

  // Only reset the deadline input when the selected torrent actually
  // changes -- like the tracker editor below, re-writing it on every status
  // tick would blow away a date the user is mid-picking.
  if (downloadsDetailsDeadlineFor !== infoHash) {
    downloadsDetailsDeadlineFor = infoHash;
    document.getElementById("downloadsDetailsDeadlineInput").value = record.deadline
      ? downloadsEpochToDatetimeLocal(record.deadline)
      : "";
  }
  document.getElementById("downloadsDetailsDeadlineRemaining").textContent = downloadsDeadlineRemainingText(record);

  // Only rebuild the tracker editor when the selected torrent actually
  // changes -- rebuilding on every status tick would blow away whatever the
  // user is mid-typing in its "add tracker" input.
  if (downloadsDetailsTrackerEditorFor !== infoHash) {
    downloadsDetailsTrackerEditorFor = infoHash;
    renderTrackerEditor(document.getElementById("downloadsDetailsTrackerEditor"), infoHash);
  }
}

// downloadsRenderRecord() only rebuilds the details panel for the currently
// displayed torrent -- but the deadline countdown must keep ticking even
// while THAT torrent produces no status update of its own (paused, stalled,
// no peers), since post_torrent_updates() only reports torrents whose
// status actually changed. A small dedicated interval (started once from
// wireDownloadsPage) refreshes just this one text field, independent of
// which torrent's status tick last fired.
function downloadsRefreshDeadlineCountdown() {
  if (!downloadsDetailsVisibleFor) return;
  const entry = downloadsRows.get(downloadsDetailsVisibleFor);
  if (!entry) return;
  document.getElementById("downloadsDetailsDeadlineRemaining").textContent = downloadsDeadlineRemainingText(
    entry.record
  );
}

// Renders bridge.downloads.explainSlowness()'s result -- built via safe DOM
// methods (not innerHTML): cause text can embed a tracker URL, which comes
// from the .torrent file/magnet and is untrusted external input.
function downloadsRenderSlownessResult(result) {
  const box = document.getElementById("downloadsDetailsSlowness");
  box.textContent = "";
  box.style.display = "block";

  if (!result.applicable) {
    const p = document.createElement("p");
    p.textContent = "Cette analyse ne s'applique qu'aux torrents activement en téléchargement.";
    box.appendChild(p);
    return;
  }

  if (result.causes.length === 0) {
    const p = document.createElement("p");
    p.textContent = "Aucune cause identifiée parmi les critères vérifiables (seeds, tracker, bande passante).";
    box.appendChild(p);
  } else {
    const list = document.createElement("ul");
    result.causes.forEach((cause) => {
      const li = document.createElement("li");
      li.textContent = cause.text;
      list.appendChild(li);
    });
    box.appendChild(list);
  }

  if (result.note) {
    const note = document.createElement("p");
    note.textContent = result.note;
    box.appendChild(note);
  }
}

// ----------------------------------------------------------------- filter

function downloadsCurrentFilterQuery() {
  return document.getElementById("downloadsSearchInput").value.trim().toLowerCase();
}

function downloadsSetRowVisibility(entry, query) {
  const name = (entry.record.name || "").toLowerCase();
  entry.el.style.display = !query || name.includes(query) ? "" : "none";
}

// Full re-scan is only needed when the query itself changes (the 'input'
// listener below) -- a per-torrent status tick only needs to reapply the
// filter to that one row, via downloadsSetRowVisibility() directly.
function downloadsApplyFilter() {
  const query = downloadsCurrentFilterQuery();
  downloadsRows.forEach((entry) => downloadsSetRowVisibility(entry, query));
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

  items.push({
    label: record && record.pinned ? "Désépingler" : "Épingler",
    onClick: () => {
      if (record && record.pinned) {
        window.bridge.downloads.unpinTorrent(infoHash);
      } else {
        window.bridge.downloads.pinTorrent(infoHash);
      }
    },
  });
  if (record && record.state === "PAUSED") {
    items.push({ label: "Reprendre", onClick: () => window.bridge.downloads.resumeTorrent(infoHash) });
  } else {
    items.push({ label: "Pause", onClick: () => window.bridge.downloads.pauseTorrent(infoHash) });
  }
  items.push({ label: "Revérifier", onClick: () => window.bridge.downloads.recheckTorrent(infoHash) });
  items.push({
    label: record && record.locked ? "Déverrouiller" : "Verrouiller (archive)",
    onClick: () => {
      if (record && record.locked) {
        window.bridge.downloads.unlockTorrent(infoHash);
      } else {
        window.bridge.downloads.lockTorrent(infoHash);
      }
    },
  });
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
  items.push({ label: "Voir la mosaïque des morceaux", onClick: () => openPieceMapDialog(infoHash, name) });
  items.push({ label: "Voir la constellation de l'essaim", onClick: () => openSwarmConstellationDialog(infoHash, name) });
  items.push({ label: "Voir la répartition du stockage", onClick: () => openStorageSunburstDialog(infoHash, name) });
  items.push({ separator: true });
  items.push({
    label: "Retirer",
    onClick: () =>
      confirmAndRemove(
        () => window.bridge.downloads.removeTorrent(infoHash, false),
        () => window.bridge.downloads.removeTorrent(infoHash, true),
        downloadsRemovalImpact([infoHash])
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
          () => hashes.forEach((h) => window.bridge.downloads.removeTorrent(h, true)),
          downloadsRemovalImpact(hashes)
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

// ------------------------------------------------------- suggestion banner
// Discrete "what should I do next" banner above the search bar. Reuses
// signals already wired elsewhere (disk_space_monitor's lowSpaceWarning via
// bridge_profile_automation.py, share_limit_service's "reached" field on
// share.recordUpdated via bridge_share.py) -- no new Python-side detection.
// Single banner: the latest event replaces whatever was showing, no queue.

const SUGGESTION_BANNER_AUTOHIDE_MS = 15000;
let suggestionBannerTimer = null;
// ponytail: per-infoHash "already notified" set, session-lifetime only (not
// cleared on torrent removal or reached->false). Good enough for a spike
// banner meant to fire once per torrent hitting its limit; revisit with a
// real reached-state cache if a torrent needs to re-notify after reset.
const shareReachedNotified = new Set();

function showSuggestionBanner(message) {
  document.getElementById("downloadsSuggestionMessage").textContent = message;
  document.getElementById("downloadsSuggestionBanner").hidden = false;
  if (suggestionBannerTimer) clearTimeout(suggestionBannerTimer);
  suggestionBannerTimer = setTimeout(hideSuggestionBanner, SUGGESTION_BANNER_AUTOHIDE_MS);
}

function hideSuggestionBanner() {
  document.getElementById("downloadsSuggestionBanner").hidden = true;
  if (suggestionBannerTimer) {
    clearTimeout(suggestionBannerTimer);
    suggestionBannerTimer = null;
  }
}

function wireSuggestionBanner() {
  document.getElementById("downloadsSuggestionCloseBtn").addEventListener("click", hideSuggestionBanner);

  window.bridge.profileAutomation.lowSpaceWarning.connect((savePath, message) => {
    showSuggestionBanner(`${message} Envisagez de déplacer ou de supprimer un torrent terminé.`);
  });

  window.bridge.share.recordUpdated.connect((row) => {
    if (!row.reached || shareReachedNotified.has(row.infoHash)) return;
    shareReachedNotified.add(row.infoHash);
    const count = shareReachedNotified.size;
    showSuggestionBanner(
      count === 1
        ? "1 torrent a atteint sa limite de partage — pensez à l'arrêter ou l'ajuster dans l'onglet Partage."
        : `${count} torrents ont atteint leur limite de partage — pensez à les arrêter ou les ajuster dans l'onglet Partage.`
    );
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
  document.getElementById("downloadsDetailsExplainSlowBtn").addEventListener("click", () => {
    const sel = downloadsSelectedHashes();
    if (sel.length !== 1) return;
    const infoHash = sel[0];
    const box = document.getElementById("downloadsDetailsSlowness");
    box.textContent = "Analyse en cours…";
    box.style.display = "block";
    window.bridge.downloads.explainSlowness(infoHash, (result) => {
      if (downloadsDetailsSlownessFor !== infoHash) return; // selection changed while awaiting the reply
      downloadsRenderSlownessResult(result);
    });
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
  document.getElementById("downloadsDetailsDeadlineSetBtn").addEventListener("click", () => {
    const sel = downloadsSelectedHashes();
    const value = document.getElementById("downloadsDetailsDeadlineInput").value;
    if (sel.length !== 1 || !value) return;
    window.bridge.downloads.setDeadline(sel[0], new Date(value).getTime() / 1000);
  });
  document.getElementById("downloadsDetailsDeadlineClearBtn").addEventListener("click", () => {
    const sel = downloadsSelectedHashes();
    if (sel.length !== 1) return;
    document.getElementById("downloadsDetailsDeadlineInput").value = "";
    window.bridge.downloads.setDeadline(sel[0], 0);
  });

  downloadsUpdateDetailsPanel(); // starts hidden -- nothing selected yet
  wireSuggestionBanner();
  setInterval(downloadsRefreshDeadlineCountdown, 1000);
}
