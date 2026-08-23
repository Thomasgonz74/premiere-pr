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
  }

  bridge.getSettings(populate);

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
    };
    bridge.saveSettings(values, (result) => {
      status.textContent = result.ok ? "Paramètres enregistrés." : result.error || "Erreur lors de l'enregistrement.";
    });
  });

  bridge.lowSpaceWarning.connect((savePath, message) => {
    status.textContent = message;
  });
}
