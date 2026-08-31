// Profile tab -- "Automation" group: bandwidth schedule, watch folder,
// disk-space warning, auto-shutdown, pause-on-battery. Mirrors
// BandwidthScheduleSection/WatchFolderSection/DiskSpaceSection/
// AutoShutdownSection/BatteryPauseSection in profile_sections.py. All five
// sub-sections are save-on-click, batched behind one shared "Enregistrer"
// button (see bridge_profile_automation.py's getSettings/saveSettings).

function paHeading(text) {
  const h = document.createElement("h3");
  h.className = "automation-heading";
  h.textContent = text;
  return h;
}

function paFieldRow(labelText, ...inputs) {
  const row = document.createElement("div");
  row.className = "field-row";
  const label = document.createElement("label");
  label.className = "field-label inline";
  label.textContent = labelText;
  row.appendChild(label);
  inputs.forEach((input) => row.appendChild(input));
  return row;
}

function paCheckboxRow(id, labelText) {
  const row = document.createElement("div");
  row.className = "field-row";
  const check = document.createElement("input");
  check.type = "checkbox";
  check.id = id;
  row.appendChild(check);
  const label = document.createElement("label");
  label.className = "field-label inline";
  label.htmlFor = id;
  label.textContent = labelText;
  row.appendChild(label);
  return { row, check };
}

function paNumberInput(id, min, max, width) {
  const input = document.createElement("input");
  input.type = "number";
  input.id = id;
  input.min = String(min);
  input.max = String(max);
  input.style.width = width;
  return input;
}

function wireProfileAutomation() {
  const bridge = window.bridge.profileAutomation;
  const dialogs = window.bridge.dialogs;
  const container = document.getElementById("profileAutomationContainer");
  const grid = document.createElement("div");
  grid.className = "form-grid";
  container.appendChild(grid);

  // -- Planification de la bande passante --------------------------------
  grid.appendChild(paHeading("Planification de la bande passante"));
  const { row: scheduleEnabledRow, check: scheduleEnabledCheck } = paCheckboxRow(
    "paScheduleEnabled",
    "Activer la plage horaire limitée"
  );
  grid.appendChild(scheduleEnabledRow);

  const scheduleStart = paNumberInput("paScheduleStart", 0, 23, "60px");
  const scheduleEnd = paNumberInput("paScheduleEnd", 0, 23, "60px");
  const scheduleRow = document.createElement("div");
  scheduleRow.className = "field-row";
  const fromLabel = document.createElement("label");
  fromLabel.className = "field-label inline";
  fromLabel.textContent = "De";
  const toLabel = document.createElement("label");
  toLabel.className = "field-label inline";
  toLabel.textContent = "à";
  scheduleRow.appendChild(fromLabel);
  scheduleRow.appendChild(scheduleStart);
  scheduleRow.appendChild(toLabel);
  scheduleRow.appendChild(scheduleEnd);
  grid.appendChild(scheduleRow);

  const scheduleDownload = paNumberInput("paScheduleDownload", 0, 1000000, "90px");
  grid.appendChild(paFieldRow("Débit descendant limité (Ko/s, 0 = illimité)", scheduleDownload));
  const scheduleUpload = paNumberInput("paScheduleUpload", 0, 1000000, "90px");
  grid.appendChild(paFieldRow("Débit montant limité (Ko/s, 0 = illimité)", scheduleUpload));

  // -- Dossier surveillé ---------------------------------------------------
  grid.appendChild(paHeading("Dossier surveillé"));
  const { row: watchEnabledRow, check: watchEnabledCheck } = paCheckboxRow(
    "paWatchEnabled",
    "Ajouter automatiquement les .torrent déposés dans ce dossier"
  );
  grid.appendChild(watchEnabledRow);

  const watchPathInput = document.createElement("input");
  watchPathInput.type = "text";
  watchPathInput.id = "paWatchPath";
  const watchBrowseBtn = document.createElement("button");
  watchBrowseBtn.id = "paWatchBrowseBtn";
  watchBrowseBtn.textContent = "Parcourir…";
  const watchRow = document.createElement("div");
  watchRow.className = "field-row";
  watchRow.appendChild(watchPathInput);
  watchRow.appendChild(watchBrowseBtn);
  grid.appendChild(watchRow);

  // -- Espace disque --------------------------------------------------------
  grid.appendChild(paHeading("Espace disque"));
  const { row: diskEnabledRow, check: diskEnabledCheck } = paCheckboxRow(
    "paDiskEnabled",
    "Avertir si l'espace libre devient trop faible"
  );
  grid.appendChild(diskEnabledRow);
  const diskThreshold = paNumberInput("paDiskThreshold", 1, 1000000, "90px");
  grid.appendChild(paFieldRow("Seuil d'alerte (Mo)", diskThreshold));

  // -- Extinction automatique + Pause sur batterie --------------------------
  grid.appendChild(paHeading("Extinction automatique et pause sur batterie"));
  const { row: shutdownEnabledRow, check: shutdownEnabledCheck } = paCheckboxRow(
    "paShutdownEnabled",
    "Éteindre l'ordinateur une fois tous les téléchargements terminés"
  );
  grid.appendChild(shutdownEnabledRow);

  const shutdownActionSelect = document.createElement("select");
  shutdownActionSelect.id = "paShutdownAction";
  const shutdownOpt = document.createElement("option");
  shutdownOpt.value = "shutdown";
  shutdownOpt.textContent = "Éteindre";
  const hibernateOpt = document.createElement("option");
  hibernateOpt.value = "hibernate";
  hibernateOpt.textContent = "Mettre en veille prolongée";
  shutdownActionSelect.appendChild(shutdownOpt);
  shutdownActionSelect.appendChild(hibernateOpt);
  grid.appendChild(paFieldRow("Action", shutdownActionSelect));

  const shutdownDelay = paNumberInput("paShutdownDelay", 0, 3600, "90px");
  grid.appendChild(paFieldRow("Délai avant extinction (s)", shutdownDelay));

  const { row: batteryEnabledRow, check: batteryEnabledCheck } = paCheckboxRow(
    "paBatteryEnabled",
    "Mettre les téléchargements en pause sur batterie"
  );
  grid.appendChild(batteryEnabledRow);

  // -- Manifeste de provenance ----------------------------------------------
  grid.appendChild(paHeading("Manifeste de provenance"));
  const { row: provenanceEnabledRow, check: provenanceEnabledCheck } = paCheckboxRow(
    "paProvenanceEnabled",
    "Écrire un manifeste de provenance à la fin de chaque téléchargement"
  );
  grid.appendChild(provenanceEnabledRow);

  // -- Réputation des pairs --------------------------------------------------
  grid.appendChild(paHeading("Réputation des pairs"));
  const { row: peerReputationEnabledRow, check: peerReputationEnabledCheck } = paCheckboxRow(
    "paPeerReputationEnabled",
    "Suivre la stabilité et l'historique de chaque pair (liste de pairs)"
  );
  grid.appendChild(peerReputationEnabledRow);

  // -- Cache des pairs locaux (LAN) -------------------------------------------
  grid.appendChild(paHeading("Cache des pairs locaux (LAN)"));
  const { row: lanPeerCacheEnabledRow, check: lanPeerCacheEnabledCheck } = paCheckboxRow(
    "paLanPeerCacheEnabled",
    "Mémoriser les pairs du réseau local pour les reconnecter plus vite"
  );
  grid.appendChild(lanPeerCacheEnabledRow);

  // -- Gouverneur de pression mémoire ---------------------------------------
  grid.appendChild(paHeading("Gouverneur de pression mémoire"));
  const { row: memoryGovernorEnabledRow, check: memoryGovernorEnabledCheck } = paCheckboxRow(
    "paMemoryGovernorEnabled",
    "Réduire temporairement l'activité si la mémoire système sature"
  );
  grid.appendChild(memoryGovernorEnabledRow);
  const memoryGovernorThreshold = paNumberInput("paMemoryGovernorThreshold", 1, 100, "70px");
  grid.appendChild(paFieldRow("Seuil de déclenchement (% mémoire utilisée)", memoryGovernorThreshold));

  // -- Mode tortue sur inactivité --------------------------------------------
  grid.appendChild(paHeading("Mode tortue sur inactivité"));
  const { row: idleEnabledRow, check: idleEnabledCheck } = paCheckboxRow(
    "paIdleEnabled",
    "Réduire la bande passante quand l'ordinateur est inactif"
  );
  grid.appendChild(idleEnabledRow);
  const idleMinutes = paNumberInput("paIdleMinutes", 1, 1440, "70px");
  grid.appendChild(paFieldRow("Délai d'inactivité avant activation (minutes)", idleMinutes));

  // -- Disque connu -----------------------------------------------------------
  // Note: contrairement aux sections ci-dessus, la liste des disques connus
  // n'est PAS batchée derrière le bouton "Enregistrer" -- ajout/suppression
  // s'appliquent immédiatement (mêmes bridge.knownDisk.saveDisk/deleteDisk),
  // même convention que la liste de flux RSS (rss.js). Seule la case
  // d'activation ci-dessous fait partie du lot enregistré par ce formulaire.
  grid.appendChild(paHeading("Action automatique à l'insertion d'un disque connu"));
  const { row: knownDiskEnabledRow, check: knownDiskEnabledCheck } = paCheckboxRow(
    "paKnownDiskEnabled",
    "Proposer une action quand un disque enregistré est inséré"
  );
  grid.appendChild(knownDiskEnabledRow);

  const knownDiskNote = document.createElement("p");
  knownDiskNote.className = "field-note";
  knownDiskNote.textContent =
    "Rien ne s'exécute automatiquement : une confirmation est toujours demandée avant toute copie.";
  grid.appendChild(knownDiskNote);

  const knownDiskLabelInput = document.createElement("input");
  knownDiskLabelInput.type = "text";
  knownDiskLabelInput.id = "paKnownDiskLabel";
  knownDiskLabelInput.placeholder = "Label du volume (ex : BACKUP_USB)";
  const knownDiskActionInput = document.createElement("input");
  knownDiskActionInput.type = "text";
  knownDiskActionInput.id = "paKnownDiskAction";
  knownDiskActionInput.placeholder = "Action associée (ex : copier vers D:\\Backups)";
  const knownDiskAddBtn = document.createElement("button");
  knownDiskAddBtn.id = "paKnownDiskAddBtn";
  knownDiskAddBtn.textContent = "Ajouter";
  const knownDiskAddRow = document.createElement("div");
  knownDiskAddRow.className = "field-row";
  knownDiskAddRow.appendChild(knownDiskLabelInput);
  knownDiskAddRow.appendChild(knownDiskActionInput);
  knownDiskAddRow.appendChild(knownDiskAddBtn);
  grid.appendChild(knownDiskAddRow);

  const knownDiskAddStatus = document.createElement("p");
  knownDiskAddStatus.className = "status-line";
  knownDiskAddStatus.id = "paKnownDiskAddStatus";
  grid.appendChild(knownDiskAddStatus);

  const knownDiskList = document.createElement("div");
  knownDiskList.className = "listbox";
  knownDiskList.id = "paKnownDiskList";
  grid.appendChild(knownDiskList);

  // -- Journal des décisions automatiques ------------------------------------
  // Lecture seule : historique de ce que les services d'automatisation ont
  // fait tout seuls (pause sur erreur disque, alerte espace disque, disque
  // connu détecté...), pas ce que l'utilisateur a fait à la main. Pas de
  // pagination/filtre -- juste les 100 dernières entrées, la plus récente en
  // premier (voir engine/decision_journal.py).
  grid.appendChild(paHeading("Journal des décisions automatiques"));
  const journalList = document.createElement("div");
  journalList.className = "listbox";
  journalList.id = "paDecisionJournalList";
  grid.appendChild(journalList);

  function renderDecisionJournal(entries) {
    journalList.replaceChildren();
    if (!entries.length) {
      const note = document.createElement("p");
      note.className = "empty-note";
      note.textContent = "Aucune décision automatique enregistrée.";
      journalList.appendChild(note);
      return;
    }
    entries.forEach((entry) => {
      const row = document.createElement("div");
      row.className = "row";

      const timeEl = document.createElement("span");
      timeEl.className = "row-name";
      timeEl.textContent = entry.timestamp;
      row.appendChild(timeEl);

      const textEl = document.createElement("span");
      textEl.textContent = entry.text;
      textEl.title = entry.text;
      row.appendChild(textEl);

      journalList.appendChild(row);
    });
  }

  bridge.getDecisionJournal(renderDecisionJournal);

  const status = document.createElement("p");
  status.className = "status-line";
  status.id = "paStatus";
  grid.appendChild(status);

  const saveBtn = document.createElement("button");
  saveBtn.className = "start-btn";
  saveBtn.id = "paSaveBtn";
  saveBtn.textContent = "Enregistrer";
  grid.appendChild(saveBtn);

  function populate(values) {
    scheduleEnabledCheck.checked = values.scheduleEnabled;
    scheduleStart.value = values.scheduleStartHour;
    scheduleEnd.value = values.scheduleEndHour;
    scheduleDownload.value = values.scheduleDownloadKbps;
    scheduleUpload.value = values.scheduleUploadKbps;
    watchEnabledCheck.checked = values.watchFolderEnabled;
    watchPathInput.value = values.watchFolderPath;
    diskEnabledCheck.checked = values.diskSpaceEnabled;
    diskThreshold.value = values.diskSpaceThresholdMb;
    shutdownEnabledCheck.checked = values.shutdownEnabled;
    shutdownActionSelect.value = values.shutdownAction;
    shutdownDelay.value = values.shutdownDelaySeconds;
    batteryEnabledCheck.checked = values.batteryPauseEnabled;
    provenanceEnabledCheck.checked = values.provenanceManifestEnabled;
    peerReputationEnabledCheck.checked = values.peerReputationEnabled;
    lanPeerCacheEnabledCheck.checked = values.lanPeerCacheEnabled;
    memoryGovernorEnabledCheck.checked = values.memoryGovernorEnabled;
    memoryGovernorThreshold.value = values.memoryGovernorThresholdPercent;
    idleEnabledCheck.checked = values.idleBandwidthReductionEnabled;
    idleMinutes.value = values.idleBandwidthReductionMinutes;
    knownDiskEnabledCheck.checked = values.knownDiskEnabled;
  }

  bridge.getSettings(populate);

  const knownDiskBridge = window.bridge.knownDisk;

  function renderKnownDisks(disks) {
    knownDiskList.replaceChildren();
    if (!disks.length) {
      const note = document.createElement("p");
      note.className = "empty-note";
      note.textContent = "Aucun disque enregistré.";
      knownDiskList.appendChild(note);
      return;
    }
    disks.forEach((disk) => {
      const row = document.createElement("div");
      row.className = "row";

      const labelEl = document.createElement("span");
      labelEl.className = "row-name";
      labelEl.textContent = disk.label;
      labelEl.title = disk.label;
      row.appendChild(labelEl);

      const actionEl = document.createElement("span");
      actionEl.textContent = disk.action;
      actionEl.title = disk.action;
      row.appendChild(actionEl);

      const actions = document.createElement("div");
      actions.className = "row-actions";
      const removeBtn = document.createElement("button");
      removeBtn.textContent = "✕";
      removeBtn.addEventListener("click", () => {
        knownDiskBridge.deleteDisk(disk.label);
        reloadKnownDisks();
      });
      actions.appendChild(removeBtn);
      row.appendChild(actions);

      knownDiskList.appendChild(row);
    });
  }

  function reloadKnownDisks() {
    knownDiskBridge.listDisks(renderKnownDisks);
  }

  reloadKnownDisks();

  knownDiskAddBtn.addEventListener("click", () => {
    const label = knownDiskLabelInput.value.trim();
    const action = knownDiskActionInput.value.trim();
    knownDiskBridge.saveDisk(label, action, (result) => {
      knownDiskAddStatus.textContent = result.error || "";
      if (result.ok) {
        knownDiskLabelInput.value = "";
        knownDiskActionInput.value = "";
        reloadKnownDisks();
      }
    });
  });

  // Le service ne fait jamais rien tout seul : ce signal informe seulement
  // l'utilisateur qu'un disque connu vient d'apparaître. `action` est un nom
  // de catégorie de torrent (voir bridge_known_disk.py) -- rien ne bouge tant
  // que l'utilisateur n'a pas cliqué sur "Confirmer et déplacer" ci-dessous,
  // et le nombre de torrents + la taille totale concernés sont affichés
  // avant ce clic.
  knownDiskBridge.diskConfirmationRequested.connect((infoJson, action) => {
    let info;
    try {
      info = JSON.parse(infoJson);
    } catch (e) {
      info = {};
    }
    const category = action || "";
    knownDiskBridge.previewCategoryMove(category, (impact) => {
      const content = document.createElement("div");
      content.className = "form-grid";

      const message = document.createElement("p");
      message.textContent = `Le disque "${info.label || "?"}" (${info.mountpoint || "?"}) est associé à la catégorie "${category}".`;
      content.appendChild(message);

      const details = document.createElement("p");
      details.className = "field-note";
      details.textContent = impact.count > 0
        ? `${impact.count} torrent(s) de cette catégorie seront déplacés vers "${info.mountpoint || "?"}\\${category}" (taille totale : ${formatSize(impact.totalSize)}).`
        : "Aucun torrent actif n'appartient à cette catégorie -- rien à déplacer.";
      content.appendChild(details);

      const buttonRow = document.createElement("div");
      buttonRow.className = "modal-close-row";

      const confirmBtn = document.createElement("button");
      confirmBtn.textContent = "Confirmer et déplacer";
      confirmBtn.disabled = impact.count === 0;
      confirmBtn.addEventListener("click", () => {
        closeModal();
        knownDiskBridge.executeCategoryMove(category, info.mountpoint || "", (result) => {
          const summary = result.errors.length
            ? `${result.moved} torrent(s) déplacé(s), ${result.errors.length} échec(s) : ${result.errors.join("; ")}`
            : `${result.moved} torrent(s) déplacé(s) avec succès.`;
          alertModal("Déplacement terminé", summary, "Fermer");
        });
      });
      buttonRow.appendChild(confirmBtn);

      const cancelBtn = document.createElement("button");
      cancelBtn.textContent = "Annuler";
      cancelBtn.addEventListener("click", () => closeModal());
      buttonRow.appendChild(cancelBtn);

      content.appendChild(buttonRow);
      openModal("Disque connu détecté", content);
    });
  });

  watchBrowseBtn.addEventListener("click", () => {
    dialogs.browseFolder(watchPathInput.value, (path) => {
      if (path) watchPathInput.value = path;
    });
  });

  saveBtn.addEventListener("click", () => {
    const values = {
      scheduleEnabled: scheduleEnabledCheck.checked,
      scheduleStartHour: parseInt(scheduleStart.value, 10) || 0,
      scheduleEndHour: parseInt(scheduleEnd.value, 10) || 0,
      scheduleDownloadKbps: parseInt(scheduleDownload.value, 10) || 0,
      scheduleUploadKbps: parseInt(scheduleUpload.value, 10) || 0,
      watchFolderEnabled: watchEnabledCheck.checked,
      watchFolderPath: watchPathInput.value,
      diskSpaceEnabled: diskEnabledCheck.checked,
      diskSpaceThresholdMb: parseInt(diskThreshold.value, 10) || 1,
      shutdownEnabled: shutdownEnabledCheck.checked,
      shutdownAction: shutdownActionSelect.value,
      shutdownDelaySeconds: parseInt(shutdownDelay.value, 10) || 0,
      batteryPauseEnabled: batteryEnabledCheck.checked,
      provenanceManifestEnabled: provenanceEnabledCheck.checked,
      peerReputationEnabled: peerReputationEnabledCheck.checked,
      lanPeerCacheEnabled: lanPeerCacheEnabledCheck.checked,
      memoryGovernorEnabled: memoryGovernorEnabledCheck.checked,
      memoryGovernorThresholdPercent: parseInt(memoryGovernorThreshold.value, 10) || 90,
      idleBandwidthReductionEnabled: idleEnabledCheck.checked,
      idleBandwidthReductionMinutes: parseInt(idleMinutes.value, 10) || 15,
      knownDiskEnabled: knownDiskEnabledCheck.checked,
    };
    bridge.saveSettings(values, (result) => {
      status.textContent = result.ok ? "Paramètres enregistrés." : result.error || "Erreur lors de l'enregistrement.";
    });
  });

  bridge.lowSpaceWarning.connect((savePath, message) => {
    status.textContent = message;
  });
}
