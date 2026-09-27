// Downloads page: full parity with native DownloadsTab -- 9-column rows
// (name/progress/ETA/DL/UL/peers-seeds/state/category/action), health-color
// backgrounds, private-torrent badge, single/multi row selection (Ctrl/Shift
// click, matching QTableWidget's ExtendedSelection), a details panel for the
// single selected torrent (current tracker, pause/resume, queue up/down,
// sequential checkbox, full tracker editor), a complete context menu
// (single + multi selection), category assignment, magnet-URI copy, and
// confirm-before-remove (with an optional delete-files choice) everywhere a
// torrent can be removed. Ported field-for-field from downloads_tab.py.

const DOWNLOADS_STATE_KEYS = {
  QUEUED: "downloads_tab.state_queued",
  CHECKING_METADATA: "downloads_tab.state_checking_metadata",
  AWAITING_ANALYSIS: "downloads_tab.state_awaiting_analysis",
  DOWNLOADING: "downloads_tab.state_downloading",
  PAUSED: "downloads_tab.state_paused",
  SEEDING: "downloads_tab.state_seeding",
  FINISHED: "downloads_tab.state_finished",
  ERROR: "downloads_tab.state_error",
};

const downloadsRows = new Map(); // infoHash -> { el, tetris, record }
let downloadsLastClickedHash = null;
let downloadsDetailsTrackerEditorFor = null;
let downloadsDetailsAllocatedFor = null;
let downloadsDetailsSlownessFor = null;
let downloadsDetailsDeadlineFor = null;
// Catalogue idea "etiquettes multiples" -- infoHash -> string[], populated
// lazily (fetched the first time a row is filtered/rendered while a tag
// filter is active, or right after an add/remove) rather than up front for
// every torrent on every render.
const downloadsTagsCache = new Map();
let downloadsTagFilterValue = "";

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
    impact.stateLabel = t(DOWNLOADS_STATE_KEYS[records[0].state]) || records[0].state;
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
  if (!record.deadline) return t("web.downloads.deadline_none");
  const remaining = record.deadline - Date.now() / 1000;
  if (remaining <= 0) return t("web.downloads.deadline_passed");
  return t("web.downloads.deadline_remaining", { eta: formatEta(remaining) });
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
  pinBtn.title = record.pinned ? t("web.downloads.unpin_label") : t("web.downloads.pin_tooltip");

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
    tooltipParts.push(t("web.downloads.locked_tooltip"));
  }
  if (record.isPrivate) {
    tooltipParts.push(t("downloads_tab.private_badge_tooltip"));
  }
  nameEl.title = tooltipParts.length > 1 ? tooltipParts.join("\n\n") : record.name;

  entry.etaEl.textContent = downloadsEta(record);
  entry.downRateEl.textContent = t("main_window.status_download_rate", { rate: formatRate(record.downloadRate) });
  entry.upRateEl.textContent = t("main_window.status_upload_rate", { rate: formatRate(record.uploadRate) });
  entry.peersEl.textContent = t("downloads_tab.peers_seeds", { peers: record.numPeers, seeds: record.numSeeds });
  entry.stateEl.textContent = t(DOWNLOADS_STATE_KEYS[record.state]) || record.state;
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
  // Its tags were cleared server-side too (see DownloadsBridge.__init__), so
  // the filter's tag list may have lost one -- only if it had any.
  // ponytail: tags never fetched this session (no tag filter or tags
  // dialog used on it) are assumed empty; such a tag lingers in the select
  // until the next refresh. Fetch before skipping if that ever matters.
  const cachedTags = downloadsTagsCache.get(infoHash);
  downloadsTagsCache.delete(infoHash);
  if (cachedTags && cachedTags.length) downloadsScheduleTagFilterRefresh();
  const entry = downloadsRows.get(infoHash);
  if (!entry) return;
  entry.el.remove();
  downloadsRows.delete(infoHash);
  if (downloadsRows.size === 0) {
    const list = document.getElementById("downloadsList");
    const note = document.createElement("p");
    note.className = "empty-note";
    note.id = "emptyNote";
    note.textContent = t("web.downloads.empty_note");
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
  document.getElementById("downloadsDetailsTracker").textContent = t("downloads_tab.tracker_current", {
    tracker: record.currentTracker || "—",
  });

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
    allocatedEl.textContent = t("web.downloads.allocated_calculating");
    window.bridge.downloads.getAllocatedSize(infoHash, (allocatedBytes) => {
      if (downloadsDetailsAllocatedFor !== infoHash) return; // selection changed while awaiting the reply
      const logicalText = formatSize(record.totalSize);
      const allocatedText = formatSize(allocatedBytes);
      allocatedEl.textContent = allocatedBytes === record.totalSize
        ? t("web.downloads.allocated_same", { allocated: allocatedText })
        : t("web.downloads.allocated_different", { allocated: allocatedText, logical: logicalText });
    });
  }

  const queueText = record.queuePosition >= 0
    ? t("downloads_tab.queue_position_value", { position: record.queuePosition + 1 })
    : t("downloads_tab.queue_position_active");
  document.getElementById("downloadsDetailsQueue").textContent = t("downloads_tab.queue_position", {
    position: queueText,
  });
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
    p.textContent = t("web.downloads.slowness_not_applicable");
    box.appendChild(p);
    return;
  }

  if (result.causes.length === 0) {
    const p = document.createElement("p");
    p.textContent = t("web.downloads.slowness_no_cause");
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
  const matchesQuery = !query || name.includes(query);
  let matchesTag = true;
  if (downloadsTagFilterValue) {
    const cached = downloadsTagsCache.get(entry.record.infoHash);
    if (cached === undefined) {
      // Not fetched yet -- hide for now (avoids a false-positive "visible"
      // flash) and refresh once the real tag list comes back.
      matchesTag = false;
      window.bridge.downloads.getTags(entry.record.infoHash, (tags) => {
        downloadsTagsCache.set(entry.record.infoHash, tags);
        downloadsSetRowVisibility(entry, downloadsCurrentFilterQuery());
      });
    } else {
      matchesTag = cached.includes(downloadsTagFilterValue);
    }
  }
  entry.el.style.display = matchesQuery && matchesTag ? "" : "none";
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
    label: record && record.pinned ? t("web.downloads.unpin_label") : t("web.downloads.pin_label"),
    onClick: () => {
      if (record && record.pinned) {
        window.bridge.downloads.unpinTorrent(infoHash);
      } else {
        window.bridge.downloads.pinTorrent(infoHash);
      }
    },
  });
  if (record && record.state === "PAUSED") {
    items.push({ label: t("common.resume"), onClick: () => window.bridge.downloads.resumeTorrent(infoHash) });
  } else {
    items.push({ label: t("common.pause"), onClick: () => window.bridge.downloads.pauseTorrent(infoHash) });
  }
  items.push({ label: t("common.context_recheck"), onClick: () => window.bridge.downloads.recheckTorrent(infoHash) });
  items.push({
    label: record && record.locked ? t("web.downloads.unlock_label") : t("web.downloads.lock_label"),
    onClick: () => {
      if (record && record.locked) {
        window.bridge.downloads.unlockTorrent(infoHash);
      } else {
        window.bridge.downloads.lockTorrent(infoHash);
      }
    },
  });
  items.push({
    label: t("common.context_move_storage"),
    onClick: () => {
      window.bridge.dialogs.browseFolder("", (path) => {
        if (path) window.bridge.downloads.moveStorage(infoHash, path);
      });
    },
  });
  items.push({ separator: true });
  items.push({
    label: t("common.context_assign_category"),
    onClick: () => downloadsOpenCategoryDialog(infoHash, record ? record.category : ""),
  });
  items.push({
    label: t("web.downloads.manage_tags_label"),
    onClick: () => downloadsOpenTagsDialog(infoHash, name),
  });
  items.push({
    label: t("common.context_copy_magnet"),
    onClick: () => {
      window.bridge.downloads.getMagnetUri(infoHash, (uri) => {
        if (uri) {
          navigator.clipboard.writeText(uri);
        } else {
          alertModal(
            t("downloads_tab.magnet_not_available_title"),
            t("downloads_tab.magnet_not_available_message")
          );
        }
      });
    },
  });
  items.push({ label: t("common.context_edit_files"), onClick: () => openFilePriorityDialog(infoHash, name) });
  items.push({ label: t("common.context_view_peers"), onClick: () => openPeerListDialog(infoHash, name) });
  items.push({ label: t("common.context_view_speed_graph"), onClick: () => openSpeedGraphDialog(infoHash, name) });
  items.push({ label: t("web.downloads.view_piece_map_label"), onClick: () => openPieceMapDialog(infoHash, name) });
  items.push({
    label: t("web.downloads.view_swarm_constellation_label"),
    onClick: () => openSwarmConstellationDialog(infoHash, name),
  });
  items.push({
    label: t("web.downloads.view_storage_sunburst_label"),
    onClick: () => openStorageSunburstDialog(infoHash, name),
  });
  items.push({ separator: true });
  items.push({
    label: t("common.remove"),
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
      label: t("common.context_pause_selection"),
      onClick: () => hashes.forEach((h) => window.bridge.downloads.pauseTorrent(h)),
    },
    {
      label: t("common.context_resume_selection"),
      onClick: () => hashes.forEach((h) => window.bridge.downloads.resumeTorrent(h)),
    },
    { separator: true },
    {
      label: t("common.context_remove_selection"),
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
    label.textContent = t("downloads_tab.category_dialog_label");
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
    saveBtn.textContent = t("profile_tab.save_button");
    saveBtn.addEventListener("click", () => {
      window.bridge.downloads.setCategory(infoHash, input.value.trim());
      closeModal();
    });
    buttonRow.appendChild(saveBtn);
    const cancelBtn = document.createElement("button");
    cancelBtn.textContent = t("common.cancel");
    cancelBtn.addEventListener("click", () => closeModal());
    buttonRow.appendChild(cancelBtn);
    content.appendChild(buttonRow);

    openModal(t("downloads_tab.category_dialog_title"), content);
  });
}

// Catalogue idea "etiquettes multiples" -- multiple free-form tags per
// torrent, alongside (not replacing) the single category above.
function downloadsRefreshTagFilterOptions() {
  window.bridge.downloads.listAllTags((tags) => {
    const select = document.getElementById("downloadsTagFilterSelect");
    const previous = select.value;
    select.replaceChildren();
    const allOpt = document.createElement("option");
    allOpt.value = "";
    allOpt.textContent = t("web.downloads.all_tags_option");
    select.appendChild(allOpt);
    tags.forEach((tag) => {
      const opt = document.createElement("option");
      opt.value = tag;
      opt.textContent = tag;
      select.appendChild(opt);
    });
    select.value = tags.includes(previous) ? previous : "";
    if (select.value !== downloadsTagFilterValue) {
      // The filtered-on tag no longer exists (e.g. its last torrent was
      // removed): drop the filter instead of hiding every row behind it.
      downloadsTagFilterValue = select.value;
      downloadsApplyFilter();
    }
  });
}

// Removing N torrents at once pushes N recordRemoved: one refresh for all.
let downloadsTagFilterRefreshTimer = null;

function downloadsScheduleTagFilterRefresh() {
  if (downloadsTagFilterRefreshTimer !== null) return;
  downloadsTagFilterRefreshTimer = setTimeout(() => {
    downloadsTagFilterRefreshTimer = null;
    downloadsRefreshTagFilterOptions();
  }, 50);
}

function downloadsOpenTagsDialog(infoHash, torrentName) {
  window.bridge.downloads.getTags(infoHash, (tags) => {
    downloadsTagsCache.set(infoHash, tags);
    const content = document.createElement("div");
    content.className = "form-grid";

    const list = document.createElement("div");
    list.className = "listbox";

    function renderTagList(currentTags) {
      list.replaceChildren();
      if (!currentTags.length) {
        const note = document.createElement("p");
        note.className = "empty-note";
        note.textContent = t("web.downloads.no_tags_note");
        list.appendChild(note);
        return;
      }
      currentTags.forEach((tag) => {
        const row = document.createElement("div");
        row.className = "row";
        const label = document.createElement("span");
        label.className = "row-name";
        label.textContent = tag;
        row.appendChild(label);
        const removeBtn = document.createElement("button");
        removeBtn.textContent = "✕";
        removeBtn.addEventListener("click", () => {
          window.bridge.downloads.removeTag(infoHash, tag);
          const updated = currentTags.filter((t) => t !== tag);
          downloadsTagsCache.set(infoHash, updated);
          renderTagList(updated);
          downloadsRefreshTagFilterOptions();
        });
        row.appendChild(removeBtn);
        list.appendChild(row);
      });
    }
    renderTagList(tags);
    content.appendChild(list);

    const addRow = document.createElement("div");
    addRow.className = "field-row";
    const addInput = document.createElement("input");
    addInput.type = "text";
    addInput.placeholder = t("web.downloads.new_tag_placeholder");
    addRow.appendChild(addInput);
    const addBtn = document.createElement("button");
    addBtn.textContent = t("common.add");
    addBtn.addEventListener("click", () => {
      const tag = addInput.value.trim();
      if (!tag) return;
      window.bridge.downloads.addTag(infoHash, tag);
      const updated = downloadsTagsCache.get(infoHash) || [];
      if (!updated.includes(tag)) updated.push(tag);
      downloadsTagsCache.set(infoHash, updated);
      renderTagList(updated);
      addInput.value = "";
      downloadsRefreshTagFilterOptions();
    });
    addRow.appendChild(addBtn);
    content.appendChild(addRow);

    const closeRow = document.createElement("div");
    closeRow.className = "modal-close-row";
    const closeBtn = document.createElement("button");
    closeBtn.textContent = t("titlebar.close");
    closeBtn.addEventListener("click", () => closeModal());
    closeRow.appendChild(closeBtn);
    content.appendChild(closeRow);

    openModal(t("web.downloads.tags_dialog_title", { name: torrentName }), content);
  });
}

// ------------------------------------------------------- suggestion banner
// Discrete "what should I do next" banner above the search bar. Reuses
// signals already wired elsewhere (disk_space_monitor's lowSpaceWarning via
// bridge_profile_automation.py, share_limit_service's "reached" field on
// share.recordUpdated/recordsUpdated via bridge_share.py) -- no new
// Python-side detection.
// Single banner: the latest event replaces whatever was showing, no queue.

const SUGGESTION_BANNER_AUTOHIDE_MS = 15000;
let suggestionBannerTimer = null;
// infoHash -> last "reached" value seen this session. `reached` is persisted
// (share_limits.json), so a row's first sighting (initial list or first push)
// only records it: a limit reached in a previous session must not be
// announced again, e.g. by the resync ShareBridge.set_live(true) sends when
// the window comes back. Only a false->true change seen here notifies.
const shareReachedSeen = new Map();
// Torrents announced this session -- the banner's count.
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
    showSuggestionBanner(`${message} ${t("web.downloads.low_space_suggestion_suffix")}`);
  });

  const notifyShareReached = (row) => {
    const before = shareReachedSeen.get(row.infoHash);
    shareReachedSeen.set(row.infoHash, row.reached);
    if (before !== false || !row.reached) return;
    shareReachedNotified.add(row.infoHash);
    const count = shareReachedNotified.size;
    showSuggestionBanner(
      count === 1
        ? t("web.downloads.share_limit_reached_singular")
        : t("web.downloads.share_limit_reached_plural", { count })
    );
  };
  // recordUpdated: the immediate "limit reached" push (sent even while the
  // window is hidden); recordsUpdated: the per-tick batch. The initial list
  // gives every tracked torrent its starting state, so a quiet one whose
  // first push is the "limit reached" one still notifies.
  window.bridge.share.recordUpdated.connect(notifyShareReached);
  window.bridge.share.recordsUpdated.connect((rows) => rows.forEach(notifyShareReached));
  window.bridge.share.listTorrents((rows) => rows.forEach(notifyShareReached));
}

// -------------------------------------------------------------------- wire

function wireDownloadsPage() {
  const bridge = window.bridge.downloads;
  bridge.recordUpdated.connect(downloadsRenderRecord);
  bridge.recordsUpdated.connect((rows) => rows.forEach(downloadsRenderRecord));
  bridge.recordRemoved.connect(downloadsRemoveRecord);
  bridge.listTorrents((initial) => initial.forEach(downloadsRenderRecord));

  document.getElementById("downloadsSearchInput").addEventListener("input", downloadsApplyFilter);

  downloadsRefreshTagFilterOptions();
  document.getElementById("downloadsTagFilterSelect").addEventListener("change", (event) => {
    downloadsTagFilterValue = event.target.value;
    downloadsApplyFilter();
  });

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
    box.textContent = t("web.downloads.slowness_analyzing");
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
