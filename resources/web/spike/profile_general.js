// Profile tab "General" group wiring. Mirrors GeneralSettingsSection +
// AudioSection from profile_sections.py: most fields batch into a single
// "Enregistrer" click (getSettings/saveSettings), while theme, appearance
// mode, language, and volume apply and persist immediately on change (see
// bridge_profile_general.py for why).

function pgFieldRow(labelText, inputEl, noteText) {
  const row = document.createElement("div");
  row.className = "field-row";
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = labelText;
  row.appendChild(label);
  row.appendChild(inputEl);
  if (noteText) {
    const note = document.createElement("span");
    note.className = "field-note";
    note.textContent = noteText;
    row.appendChild(note);
  }
  return row;
}

function pgCheckboxRow(id, labelText) {
  const row = document.createElement("label");
  row.className = "field-row";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.id = id;
  row.appendChild(input);
  row.appendChild(document.createTextNode(labelText));
  return { row, input };
}

function pgPopulateSelect(select, options, currentValue) {
  select.replaceChildren();
  options.forEach((opt) => {
    const el = document.createElement("option");
    el.value = opt.id;
    el.textContent = opt.label;
    select.appendChild(el);
  });
  select.value = currentValue;
}

function wireProfileGeneral() {
  const bridge = window.bridge.profileGeneral;
  const dialogs = window.bridge.dialogs;
  const container = document.getElementById("profileGeneralContainer");

  const heading = document.createElement("h3");
  heading.textContent = "Général";
  container.appendChild(heading);

  // ---- Téléchargements ----
  const dlHeading = document.createElement("h4");
  dlHeading.className = "profile-subheading";
  dlHeading.textContent = "Téléchargements";
  container.appendChild(dlHeading);

  const dlGrid = document.createElement("div");
  dlGrid.className = "form-grid";
  container.appendChild(dlGrid);

  const destInput = document.createElement("input");
  destInput.type = "text";
  destInput.id = "pgDestInput";
  const destBrowseBtn = document.createElement("button");
  destBrowseBtn.id = "pgDestBrowseBtn";
  destBrowseBtn.textContent = "Parcourir...";
  const destRow = pgFieldRow("Dossier de destination par défaut :", destInput);
  destRow.appendChild(destBrowseBtn);
  dlGrid.appendChild(destRow);

  const downloadLimitInput = document.createElement("input");
  downloadLimitInput.type = "number";
  downloadLimitInput.id = "pgDownloadLimit";
  downloadLimitInput.min = "0";
  downloadLimitInput.max = "1000000";
  dlGrid.appendChild(pgFieldRow("Limite de téléchargement :", downloadLimitInput, "Ko/s (0 = illimité)"));

  const uploadLimitInput = document.createElement("input");
  uploadLimitInput.type = "number";
  uploadLimitInput.id = "pgUploadLimit";
  uploadLimitInput.min = "0";
  uploadLimitInput.max = "1000000";
  dlGrid.appendChild(pgFieldRow("Limite d'envoi :", uploadLimitInput, "Ko/s (0 = illimité)"));

  const maxActiveInput = document.createElement("input");
  maxActiveInput.type = "number";
  maxActiveInput.id = "pgMaxActive";
  maxActiveInput.min = "1";
  maxActiveInput.max = "100";
  dlGrid.appendChild(pgFieldRow("Téléchargements actifs simultanés maximum :", maxActiveInput));

  const dangerThresholdInput = document.createElement("input");
  dangerThresholdInput.type = "number";
  dangerThresholdInput.id = "pgDangerThreshold";
  dangerThresholdInput.min = "0";
  dangerThresholdInput.max = "100";
  dlGrid.appendChild(pgFieldRow("Seuil d'auto-exclusion des fichiers dangereux :", dangerThresholdInput, "%"));

  const notif = pgCheckboxRow("pgNotifications", "Notifier la fin d'un téléchargement ou d'un partage");
  dlGrid.appendChild(notif.row);
  const launch = pgCheckboxRow("pgLaunchAtStartup", "Lancer automatiquement au démarrage de Windows");
  dlGrid.appendChild(launch.row);
  const updates = pgCheckboxRow("pgCheckForUpdates", "Vérifier les mises à jour au démarrage");
  dlGrid.appendChild(updates.row);
  const tray = pgCheckboxRow("pgMinimizeToTray", "Réduire dans la barre système");
  dlGrid.appendChild(tray.row);

  const saveBtn = document.createElement("button");
  saveBtn.className = "start-btn";
  saveBtn.id = "pgSaveBtn";
  saveBtn.textContent = "Enregistrer";
  container.appendChild(saveBtn);

  const status = document.createElement("p");
  status.className = "status-line";
  status.id = "pgStatus";
  container.appendChild(status);

  // ---- Apparence ----
  const appearanceHeading = document.createElement("h4");
  appearanceHeading.className = "profile-subheading";
  appearanceHeading.textContent = "Apparence";
  container.appendChild(appearanceHeading);

  const appearanceGrid = document.createElement("div");
  appearanceGrid.className = "form-grid";
  container.appendChild(appearanceGrid);

  const themeSelect = document.createElement("select");
  themeSelect.id = "pgThemeSelect";
  appearanceGrid.appendChild(pgFieldRow("Thème (base Windows XP) :", themeSelect));

  const appearanceSelect = document.createElement("select");
  appearanceSelect.id = "pgAppearanceSelect";
  appearanceGrid.appendChild(pgFieldRow("Mode d'affichage :", appearanceSelect));

  const languageSelect = document.createElement("select");
  languageSelect.id = "pgLanguageSelect";
  appearanceGrid.appendChild(pgFieldRow("Langue :", languageSelect));

  // ---- Audio ----
  const audioHeading = document.createElement("h4");
  audioHeading.className = "profile-subheading";
  audioHeading.textContent = "Audio";
  container.appendChild(audioHeading);

  const audioGrid = document.createElement("div");
  audioGrid.className = "form-grid";
  container.appendChild(audioGrid);

  const volumeSlider = document.createElement("input");
  volumeSlider.type = "range";
  volumeSlider.id = "pgVolumeSlider";
  volumeSlider.min = "0";
  volumeSlider.max = "100";
  const volumeValue = document.createElement("span");
  volumeValue.id = "pgVolumeValue";
  const volumeRow = pgFieldRow("Volume", volumeSlider);
  volumeRow.appendChild(volumeValue);
  audioGrid.appendChild(volumeRow);

  const audioNote = document.createElement("p");
  audioNote.className = "field-note";
  audioNote.textContent = "Contrôle le volume de l'hymne joué en fond sonore par le thème CCCP.";
  audioGrid.appendChild(audioNote);

  // ---- Populate + wire ----
  destBrowseBtn.addEventListener("click", () => {
    dialogs.browseFolder(destInput.value, (path) => {
      if (path) destInput.value = path;
    });
  });

  saveBtn.addEventListener("click", () => {
    const values = {
      defaultDownloadDir: destInput.value,
      downloadRateLimitKbps: parseInt(downloadLimitInput.value, 10) || 0,
      uploadRateLimitKbps: parseInt(uploadLimitInput.value, 10) || 0,
      maxActiveDownloads: parseInt(maxActiveInput.value, 10) || 1,
      dangerAutoExcludeThreshold: parseInt(dangerThresholdInput.value, 10) || 0,
      notificationsEnabled: notif.input.checked,
      launchAtStartup: launch.input.checked,
      checkForUpdates: updates.input.checked,
      minimizeToTray: tray.input.checked,
    };
    bridge.saveSettings(values, (result) => {
      status.textContent = result.ok ? "Paramètres enregistrés." : result.error || "";
    });
  });

  themeSelect.addEventListener("change", () => bridge.setTheme(themeSelect.value));
  appearanceSelect.addEventListener("change", () => bridge.setAppearanceMode(appearanceSelect.value));
  languageSelect.addEventListener("change", () => bridge.setLanguage(languageSelect.value));

  volumeSlider.addEventListener("input", () => {
    volumeValue.textContent = `${volumeSlider.value}%`;
  });
  volumeSlider.addEventListener("change", () => {
    bridge.setVolume(parseInt(volumeSlider.value, 10));
  });

  bridge.getSettings((values) => {
    destInput.value = values.defaultDownloadDir;
    downloadLimitInput.value = values.downloadRateLimitKbps;
    uploadLimitInput.value = values.uploadRateLimitKbps;
    maxActiveInput.value = values.maxActiveDownloads;
    dangerThresholdInput.value = values.dangerAutoExcludeThreshold;
    notif.input.checked = values.notificationsEnabled;
    updates.input.checked = values.checkForUpdates;
    tray.input.checked = values.minimizeToTray;
    volumeSlider.value = values.audioVolume;
    volumeValue.textContent = `${values.audioVolume}%`;

    bridge.getThemeOptions((options) => pgPopulateSelect(themeSelect, options, values.theme));
    bridge.getAppearanceModeOptions((options) => pgPopulateSelect(appearanceSelect, options, values.appearanceMode));
    bridge.getLanguageOptions((options) => pgPopulateSelect(languageSelect, options, values.language));
  });

  // Reflects the real HKCU Run key rather than the possibly-stale saved
  // setting, same as native (see bridge_profile_general.py).
  bridge.getLaunchAtStartupActual((actual) => {
    launch.input.checked = actual;
  });
}
