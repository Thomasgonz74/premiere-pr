// Profile / Stats page wiring: LevelingSection + HistorySection
// (see profile_sections.py). Both are read-only display -- no
// getSettings/saveSettings pair here, just a pushed snapshot + a
// full-refresh-on-change history table, mirroring the native widgets.

const HISTORY_EVENT_LABELS = { removed: "Retiré" };

function statsFormatSnapshot(snap) {
  document.getElementById("statsLevelValue").textContent = `Niveau ${snap.level}`;
  const percent = Math.round(snap.progressToNext * 100);
  document.getElementById("statsProgressFill").style.width = `${percent}%`;
  document.getElementById("statsProgressLabel").textContent = `${percent}%`;
  document.getElementById("statsTotalsLabel").textContent =
    `Téléchargé : ${formatSize(snap.totalDownloaded)}  —  Envoyé : ${formatSize(snap.totalUploaded)}`;
}

function statsRenderHistory(entries) {
  const body = document.getElementById("statsHistoryBody");
  body.replaceChildren();
  if (!entries.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = "Aucun historique pour l'instant.";
    body.appendChild(note);
    return;
  }
  entries.forEach((entry) => {
    const row = document.createElement("div");
    row.className = "history-row";

    const nameEl = document.createElement("span");
    nameEl.className = "history-name";
    nameEl.textContent = entry.name; // safe: .textContent, entry.name comes from torrent metadata
    nameEl.title = entry.name;
    row.appendChild(nameEl);

    const sizeEl = document.createElement("span");
    sizeEl.className = "history-cell";
    sizeEl.textContent = formatSize(entry.totalSize);
    row.appendChild(sizeEl);

    const downEl = document.createElement("span");
    downEl.className = "history-cell";
    downEl.textContent = formatSize(entry.totalDownloaded);
    row.appendChild(downEl);

    const upEl = document.createElement("span");
    upEl.className = "history-cell";
    upEl.textContent = formatSize(entry.totalUploaded);
    row.appendChild(upEl);

    const dateEl = document.createElement("span");
    dateEl.className = "history-cell";
    dateEl.textContent = entry.finishedAt;
    row.appendChild(dateEl);

    const eventEl = document.createElement("span");
    eventEl.className = "history-cell";
    eventEl.textContent = HISTORY_EVENT_LABELS[entry.event] || entry.event;
    row.appendChild(eventEl);

    body.appendChild(row);
  });
}

function statsRefreshHistory(bridge) {
  bridge.getHistoryEntries((entries) => statsRenderHistory(entries));
}

function buildProfileStatsSection() {
  const container = document.getElementById("profileStatsContainer");

  const levelGroup = document.createElement("div");
  levelGroup.className = "form-grid";
  const levelHeading = document.createElement("h3");
  levelHeading.className = "profile-section-heading";
  levelHeading.textContent = "Niveau et statistiques";
  levelGroup.appendChild(levelHeading);

  const levelValue = document.createElement("p");
  levelValue.id = "statsLevelValue";
  levelValue.className = "field-label";
  levelGroup.appendChild(levelValue);

  const progressTrack = document.createElement("div");
  progressTrack.className = "level-progress-track";
  const progressFill = document.createElement("div");
  progressFill.id = "statsProgressFill";
  progressFill.className = "level-progress-fill";
  progressTrack.appendChild(progressFill);
  levelGroup.appendChild(progressTrack);

  const progressLabel = document.createElement("p");
  progressLabel.id = "statsProgressLabel";
  progressLabel.className = "field-note";
  levelGroup.appendChild(progressLabel);

  const totalsLabel = document.createElement("p");
  totalsLabel.id = "statsTotalsLabel";
  totalsLabel.className = "field-label";
  levelGroup.appendChild(totalsLabel);

  container.appendChild(levelGroup);

  const historyGroup = document.createElement("div");
  historyGroup.className = "form-grid";
  const historyHeading = document.createElement("h3");
  historyHeading.className = "profile-section-heading";
  historyHeading.textContent = "Historique";
  historyGroup.appendChild(historyHeading);

  const historyHeader = document.createElement("div");
  historyHeader.className = "history-row history-header";
  ["Nom", "Taille", "Téléchargé", "Envoyé", "Terminé le", "Événement"].forEach((label) => {
    const cell = document.createElement("span");
    cell.textContent = label;
    historyHeader.appendChild(cell);
  });
  historyGroup.appendChild(historyHeader);

  const historyBody = document.createElement("div");
  historyBody.id = "statsHistoryBody";
  historyBody.className = "listbox";
  historyGroup.appendChild(historyBody);

  const buttonRow = document.createElement("div");
  buttonRow.className = "field-row";
  const exportBtn = document.createElement("button");
  exportBtn.id = "statsExportCsvBtn";
  exportBtn.textContent = "Exporter CSV";
  buttonRow.appendChild(exportBtn);
  const clearBtn = document.createElement("button");
  clearBtn.id = "statsClearHistoryBtn";
  clearBtn.textContent = "Effacer l'historique";
  buttonRow.appendChild(clearBtn);
  historyGroup.appendChild(buttonRow);

  const historyStatus = document.createElement("p");
  historyStatus.id = "statsHistoryStatus";
  historyStatus.className = "status-line";
  historyGroup.appendChild(historyStatus);

  container.appendChild(historyGroup);
}

function wireProfileStats() {
  buildProfileStatsSection();

  const bridge = window.bridge.profileStats;
  const dialogs = window.bridge.dialogs;

  bridge.getStatsSnapshot((snap) => statsFormatSnapshot(snap));
  bridge.snapshotUpdated.connect(statsFormatSnapshot);

  statsRefreshHistory(bridge);
  bridge.historyChanged.connect(() => statsRefreshHistory(bridge));

  document.getElementById("statsExportCsvBtn").addEventListener("click", () => {
    dialogs.browseSaveFile("torrent2000_historique.csv", "CSV (*.csv)", (path) => {
      if (!path) return;
      bridge.exportHistoryCsv(path, (result) => {
        document.getElementById("statsHistoryStatus").textContent = result.ok
          ? "Export réussi."
          : result.error || "Échec de l'export.";
      });
    });
  });

  document.getElementById("statsClearHistoryBtn").addEventListener("click", () => {
    if (!confirm("Effacer tout l'historique ? Cette action est irréversible.")) return;
    bridge.clearHistory(() => {
      document.getElementById("statsHistoryStatus").textContent = "Historique effacé.";
    });
  });
}
