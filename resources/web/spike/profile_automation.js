// Profile tab -- "Automation" group: bandwidth schedule, watch folder,
// disk-space warning, auto-shutdown, pause-on-battery. Mirrors
// BandwidthScheduleSection/WatchFolderSection/DiskSpaceSection/
// AutoShutdownSection/BatteryPauseSection in profile_sections.py. All five
// sub-sections are save-on-click, batched behind one shared "Enregistrer"
// button (see bridge_profile_automation.py's getSettings/saveSettings).

function paHeading(key) {
  const h = document.createElement("h3");
  h.className = "automation-heading";
  h.textContent = t(key);
  h.dataset.i18nKey = key;
  return h;
}

function paFieldRow(labelKey, ...inputs) {
  const row = document.createElement("div");
  row.className = "field-row";
  const label = document.createElement("label");
  label.className = "field-label inline";
  label.textContent = t(labelKey);
  label.dataset.i18nKey = labelKey;
  row.appendChild(label);
  inputs.forEach((input) => row.appendChild(input));
  return row;
}

function paCheckboxRow(id, labelKey) {
  const row = document.createElement("div");
  row.className = "field-row";
  const check = document.createElement("input");
  check.type = "checkbox";
  check.id = id;
  row.appendChild(check);
  const label = document.createElement("label");
  label.className = "field-label inline";
  label.htmlFor = id;
  label.textContent = t(labelKey);
  label.dataset.i18nKey = labelKey;
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
  grid.appendChild(paHeading("profile_tab.schedule_group"));
  const { row: scheduleEnabledRow, check: scheduleEnabledCheck } = paCheckboxRow(
    "paScheduleEnabled",
    "web.profile_automation.schedule_enabled_checkbox"
  );
  grid.appendChild(scheduleEnabledRow);

  const scheduleStart = paNumberInput("paScheduleStart", 0, 23, "60px");
  const scheduleEnd = paNumberInput("paScheduleEnd", 0, 23, "60px");
  const scheduleRow = document.createElement("div");
  scheduleRow.className = "field-row";
  const fromLabel = document.createElement("label");
  fromLabel.className = "field-label inline";
  fromLabel.textContent = t("profile_tab.schedule_from");
  fromLabel.dataset.i18nKey = "profile_tab.schedule_from";
  const toLabel = document.createElement("label");
  toLabel.className = "field-label inline";
  toLabel.textContent = t("profile_tab.schedule_to");
  toLabel.dataset.i18nKey = "profile_tab.schedule_to";
  scheduleRow.appendChild(fromLabel);
  scheduleRow.appendChild(scheduleStart);
  scheduleRow.appendChild(toLabel);
  scheduleRow.appendChild(scheduleEnd);
  grid.appendChild(scheduleRow);

  const scheduleDownload = paNumberInput("paScheduleDownload", 0, 1000000, "90px");
  grid.appendChild(paFieldRow("web.profile_automation.schedule_download_label", scheduleDownload));
  const scheduleUpload = paNumberInput("paScheduleUpload", 0, 1000000, "90px");
  grid.appendChild(paFieldRow("web.profile_automation.schedule_upload_label", scheduleUpload));

  // -- Dossier surveillé ---------------------------------------------------
  grid.appendChild(paHeading("profile_tab.watch_folder_group"));
  const { row: watchEnabledRow, check: watchEnabledCheck } = paCheckboxRow(
    "paWatchEnabled",
    "web.profile_automation.watch_folder_enabled_checkbox"
  );
  grid.appendChild(watchEnabledRow);

  const watchPathInput = document.createElement("input");
  watchPathInput.type = "text";
  watchPathInput.id = "paWatchPath";
  const watchBrowseBtn = document.createElement("button");
  watchBrowseBtn.id = "paWatchBrowseBtn";
  watchBrowseBtn.textContent = t("web.profile_automation.browse_button");
  watchBrowseBtn.dataset.i18nKey = "web.profile_automation.browse_button";
  const watchRow = document.createElement("div");
  watchRow.className = "field-row";
  watchRow.appendChild(watchPathInput);
  watchRow.appendChild(watchBrowseBtn);
  grid.appendChild(watchRow);

  // -- Espace disque --------------------------------------------------------
  grid.appendChild(paHeading("profile_tab.disk_space_group"));
  const { row: diskEnabledRow, check: diskEnabledCheck } = paCheckboxRow(
    "paDiskEnabled",
    "web.profile_automation.disk_space_enabled_checkbox"
  );
  grid.appendChild(diskEnabledRow);
  const diskThreshold = paNumberInput("paDiskThreshold", 1, 1000000, "90px");
  grid.appendChild(paFieldRow("web.profile_automation.disk_threshold_label", diskThreshold));

  // -- Extinction automatique + Pause sur batterie --------------------------
  grid.appendChild(paHeading("web.profile_automation.shutdown_battery_heading"));
  const { row: shutdownEnabledRow, check: shutdownEnabledCheck } = paCheckboxRow(
    "paShutdownEnabled",
    "profile_tab.shutdown_enabled"
  );
  grid.appendChild(shutdownEnabledRow);

  const shutdownActionSelect = document.createElement("select");
  shutdownActionSelect.id = "paShutdownAction";
  const shutdownOpt = document.createElement("option");
  shutdownOpt.value = "shutdown";
  shutdownOpt.textContent = t("shutdown_action.shutdown");
  shutdownOpt.dataset.i18nKey = "shutdown_action.shutdown";
  const hibernateOpt = document.createElement("option");
  hibernateOpt.value = "hibernate";
  hibernateOpt.textContent = t("shutdown_action.hibernate");
  hibernateOpt.dataset.i18nKey = "shutdown_action.hibernate";
  shutdownActionSelect.appendChild(shutdownOpt);
  shutdownActionSelect.appendChild(hibernateOpt);
  grid.appendChild(paFieldRow("web.profile_automation.shutdown_action_label", shutdownActionSelect));

  const shutdownDelay = paNumberInput("paShutdownDelay", 0, 3600, "90px");
  grid.appendChild(paFieldRow("web.profile_automation.shutdown_delay_label", shutdownDelay));

  const { row: batteryEnabledRow, check: batteryEnabledCheck } = paCheckboxRow(
    "paBatteryEnabled",
    "profile_tab.battery_pause_checkbox"
  );
  grid.appendChild(batteryEnabledRow);

  // -- Manifeste de provenance ----------------------------------------------
  grid.appendChild(paHeading("web.profile_automation.provenance_heading"));
  const { row: provenanceEnabledRow, check: provenanceEnabledCheck } = paCheckboxRow(
    "paProvenanceEnabled",
    "web.profile_automation.provenance_enabled_checkbox"
  );
  grid.appendChild(provenanceEnabledRow);

  // -- Réputation des pairs --------------------------------------------------
  grid.appendChild(paHeading("web.profile_automation.peer_reputation_heading"));
  const { row: peerReputationEnabledRow, check: peerReputationEnabledCheck } = paCheckboxRow(
    "paPeerReputationEnabled",
    "web.profile_automation.peer_reputation_enabled_checkbox"
  );
  grid.appendChild(peerReputationEnabledRow);

  // -- Cache des pairs locaux (LAN) -------------------------------------------
  grid.appendChild(paHeading("web.profile_automation.lan_peer_cache_heading"));
  const { row: lanPeerCacheEnabledRow, check: lanPeerCacheEnabledCheck } = paCheckboxRow(
    "paLanPeerCacheEnabled",
    "web.profile_automation.lan_peer_cache_enabled_checkbox"
  );
  grid.appendChild(lanPeerCacheEnabledRow);

  // -- Gouverneur de pression mémoire ---------------------------------------
  grid.appendChild(paHeading("web.profile_automation.memory_governor_heading"));
  const { row: memoryGovernorEnabledRow, check: memoryGovernorEnabledCheck } = paCheckboxRow(
    "paMemoryGovernorEnabled",
    "web.profile_automation.memory_governor_enabled_checkbox"
  );
  grid.appendChild(memoryGovernorEnabledRow);
  const memoryGovernorThreshold = paNumberInput("paMemoryGovernorThreshold", 1, 100, "70px");
  grid.appendChild(paFieldRow("web.profile_automation.memory_governor_threshold_label", memoryGovernorThreshold));

  // -- Mode tortue sur inactivité --------------------------------------------
  grid.appendChild(paHeading("web.profile_automation.idle_turtle_heading"));
  const { row: idleEnabledRow, check: idleEnabledCheck } = paCheckboxRow(
    "paIdleEnabled",
    "web.profile_automation.idle_enabled_checkbox"
  );
  grid.appendChild(idleEnabledRow);
  const idleMinutes = paNumberInput("paIdleMinutes", 1, 1440, "70px");
  grid.appendChild(paFieldRow("web.profile_automation.idle_minutes_label", idleMinutes));

  // -- Contrôle d'intégrité planifié --------------------------------------------
  grid.appendChild(paHeading("web.profile_automation.scheduled_recheck_heading"));
  const { row: scheduledRecheckEnabledRow, check: scheduledRecheckEnabledCheck } = paCheckboxRow(
    "paScheduledRecheckEnabled",
    "web.profile_automation.scheduled_recheck_enabled_checkbox"
  );
  grid.appendChild(scheduledRecheckEnabledRow);
  const scheduledRecheckInterval = paNumberInput("paScheduledRecheckInterval", 1, 365, "70px");
  grid.appendChild(paFieldRow("web.profile_automation.scheduled_recheck_interval_label", scheduledRecheckInterval));

  // -- Presse-papiers -----------------------------------------------------------
  grid.appendChild(paHeading("web.profile_automation.clipboard_heading"));
  const { row: clipboardEnabledRow, check: clipboardEnabledCheck } = paCheckboxRow(
    "paClipboardMagnetEnabled",
    "web.profile_automation.clipboard_enabled_checkbox"
  );
  grid.appendChild(clipboardEnabledRow);

  // -- Disque connu -----------------------------------------------------------
  // Note: contrairement aux sections ci-dessus, la liste des disques connus
  // n'est PAS batchée derrière le bouton "Enregistrer" -- ajout/suppression
  // s'appliquent immédiatement (mêmes bridge.knownDisk.saveDisk/deleteDisk),
  // même convention que la liste de flux RSS (rss.js). Seule la case
  // d'activation ci-dessous fait partie du lot enregistré par ce formulaire.
  grid.appendChild(paHeading("web.profile_automation.known_disk_heading"));
  const { row: knownDiskEnabledRow, check: knownDiskEnabledCheck } = paCheckboxRow(
    "paKnownDiskEnabled",
    "web.profile_automation.known_disk_enabled_checkbox"
  );
  grid.appendChild(knownDiskEnabledRow);

  const knownDiskNote = document.createElement("p");
  knownDiskNote.className = "field-note";
  knownDiskNote.textContent = t("web.profile_automation.known_disk_note");
  knownDiskNote.dataset.i18nKey = "web.profile_automation.known_disk_note";
  grid.appendChild(knownDiskNote);

  const knownDiskLabelInput = document.createElement("input");
  knownDiskLabelInput.type = "text";
  knownDiskLabelInput.id = "paKnownDiskLabel";
  knownDiskLabelInput.placeholder = t("web.profile_automation.known_disk_label_placeholder");
  knownDiskLabelInput.dataset.i18nPlaceholder = "web.profile_automation.known_disk_label_placeholder";
  const knownDiskActionInput = document.createElement("input");
  knownDiskActionInput.type = "text";
  knownDiskActionInput.id = "paKnownDiskAction";
  knownDiskActionInput.placeholder = t("web.profile_automation.known_disk_action_placeholder");
  knownDiskActionInput.dataset.i18nPlaceholder = "web.profile_automation.known_disk_action_placeholder";
  const knownDiskAddBtn = document.createElement("button");
  knownDiskAddBtn.id = "paKnownDiskAddBtn";
  knownDiskAddBtn.textContent = t("common.add");
  knownDiskAddBtn.dataset.i18nKey = "common.add";
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
  grid.appendChild(paHeading("web.profile_automation.decision_journal_heading"));
  const journalList = document.createElement("div");
  journalList.className = "listbox";
  journalList.id = "paDecisionJournalList";
  grid.appendChild(journalList);

  function renderDecisionJournal(entries) {
    journalList.replaceChildren();
    if (!entries.length) {
      const note = document.createElement("p");
      note.className = "empty-note";
      note.textContent = t("web.profile_automation.decision_journal_empty");
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
  saveBtn.textContent = t("profile_tab.save_button");
  saveBtn.dataset.i18nKey = "profile_tab.save_button";
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
    scheduledRecheckEnabledCheck.checked = values.scheduledRecheckEnabled;
    scheduledRecheckInterval.value = values.scheduledRecheckIntervalDays;
    clipboardEnabledCheck.checked = values.clipboardMagnetDetectionEnabled;
    knownDiskEnabledCheck.checked = values.knownDiskEnabled;
  }

  bridge.getSettings(populate);

  const knownDiskBridge = window.bridge.knownDisk;
  let paKnownDisks = [];

  function renderKnownDisks(disks) {
    knownDiskList.replaceChildren();
    if (!disks.length) {
      const note = document.createElement("p");
      note.className = "empty-note";
      note.textContent = t("web.profile_automation.known_disk_empty");
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
        // Fire-and-forget mutation with a deterministic result -- filter
        // the locally-held list and re-render instead of a round-trip
        // re-fetch of what was just removed.
        paKnownDisks = paKnownDisks.filter((d) => d.label !== disk.label);
        renderKnownDisks(paKnownDisks);
      });
      actions.appendChild(removeBtn);
      row.appendChild(actions);

      knownDiskList.appendChild(row);
    });
  }

  function reloadKnownDisks() {
    knownDiskBridge.listDisks((disks) => {
      paKnownDisks = disks;
      renderKnownDisks(disks);
    });
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
      message.textContent = t("web.profile_automation.known_disk_confirm_message", {
        label: info.label || "?",
        mountpoint: info.mountpoint || "?",
        category,
      });
      content.appendChild(message);

      const details = document.createElement("p");
      details.className = "field-note";
      details.textContent = impact.count > 0
        ? t("web.profile_automation.known_disk_impact_message", {
            count: impact.count,
            mountpoint: info.mountpoint || "?",
            category,
            totalSize: formatSize(impact.totalSize),
          })
        : t("web.profile_automation.known_disk_impact_none");
      content.appendChild(details);

      const buttonRow = document.createElement("div");
      buttonRow.className = "modal-close-row";

      const confirmBtn = document.createElement("button");
      confirmBtn.textContent = t("web.profile_automation.known_disk_confirm_button");
      confirmBtn.disabled = impact.count === 0;
      confirmBtn.addEventListener("click", () => {
        closeModal();
        knownDiskBridge.executeCategoryMove(category, info.mountpoint || "", (result) => {
          const summary = result.errors.length
            ? t("web.profile_automation.known_disk_move_result_errors", {
                moved: result.moved,
                errorCount: result.errors.length,
                errors: result.errors.join("; "),
              })
            : t("web.profile_automation.known_disk_move_result_success", { moved: result.moved });
          alertModal(t("notifications.storage_moved_title"), summary, t("titlebar.close"));
        });
      });
      buttonRow.appendChild(confirmBtn);

      const cancelBtn = document.createElement("button");
      cancelBtn.textContent = t("common.cancel");
      cancelBtn.addEventListener("click", () => closeModal());
      buttonRow.appendChild(cancelBtn);

      content.appendChild(buttonRow);
      openModal(t("web.profile_automation.known_disk_modal_title"), content);
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
      scheduledRecheckEnabled: scheduledRecheckEnabledCheck.checked,
      scheduledRecheckIntervalDays: parseInt(scheduledRecheckInterval.value, 10) || 30,
      clipboardMagnetDetectionEnabled: clipboardEnabledCheck.checked,
      knownDiskEnabled: knownDiskEnabledCheck.checked,
    };
    bridge.saveSettings(values, (result) => {
      status.textContent = result.ok ? t("web.profile_automation.settings_saved") : result.error || t("web.profile_automation.save_error");
    });
  });

  bridge.lowSpaceWarning.connect((savePath, message) => {
    status.textContent = message;
  });
}
