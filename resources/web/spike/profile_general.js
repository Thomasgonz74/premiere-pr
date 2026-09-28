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
  label.textContent = t(labelText);
  label.dataset.i18nKey = labelText;
  row.appendChild(label);
  row.appendChild(inputEl);
  if (noteText) {
    const note = document.createElement("span");
    note.className = "field-note";
    note.textContent = t(noteText);
    note.dataset.i18nKey = noteText;
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
  const labelSpan = document.createElement("span");
  labelSpan.textContent = t(labelText);
  labelSpan.dataset.i18nKey = labelText;
  row.appendChild(labelSpan);
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
  heading.textContent = t("web.profile_general.heading");
  heading.dataset.i18nKey = "web.profile_general.heading";
  container.appendChild(heading);

  // ---- Téléchargements ----
  const dlHeading = document.createElement("h4");
  dlHeading.className = "profile-subheading";
  dlHeading.textContent = t("web.profile_general.downloads_heading");
  dlHeading.dataset.i18nKey = "web.profile_general.downloads_heading";
  container.appendChild(dlHeading);

  const dlGrid = document.createElement("div");
  dlGrid.className = "form-grid";
  container.appendChild(dlGrid);

  const destInput = document.createElement("input");
  destInput.type = "text";
  destInput.id = "pgDestInput";
  const destBrowseBtn = document.createElement("button");
  destBrowseBtn.id = "pgDestBrowseBtn";
  destBrowseBtn.textContent = t("common.browse");
  destBrowseBtn.dataset.i18nKey = "common.browse";
  const destRow = pgFieldRow("profile_tab.default_download_dir", destInput);
  destRow.appendChild(destBrowseBtn);
  dlGrid.appendChild(destRow);

  const downloadLimitInput = document.createElement("input");
  downloadLimitInput.type = "number";
  downloadLimitInput.id = "pgDownloadLimit";
  downloadLimitInput.min = "0";
  downloadLimitInput.max = "1000000";
  dlGrid.appendChild(pgFieldRow("profile_tab.download_limit", downloadLimitInput, "common.kbps_unlimited_suffix"));

  const uploadLimitInput = document.createElement("input");
  uploadLimitInput.type = "number";
  uploadLimitInput.id = "pgUploadLimit";
  uploadLimitInput.min = "0";
  uploadLimitInput.max = "1000000";
  dlGrid.appendChild(pgFieldRow("profile_tab.upload_limit", uploadLimitInput, "common.kbps_unlimited_suffix"));

  const maxActiveInput = document.createElement("input");
  maxActiveInput.type = "number";
  maxActiveInput.id = "pgMaxActive";
  maxActiveInput.min = "1";
  maxActiveInput.max = "100";
  dlGrid.appendChild(pgFieldRow("profile_tab.max_active_downloads", maxActiveInput));

  const dangerThresholdInput = document.createElement("input");
  dangerThresholdInput.type = "number";
  dangerThresholdInput.id = "pgDangerThreshold";
  dangerThresholdInput.min = "0";
  dangerThresholdInput.max = "100";
  dlGrid.appendChild(pgFieldRow("profile_tab.danger_threshold", dangerThresholdInput, "%"));

  const notif = pgCheckboxRow("pgNotifications", "profile_tab.notifications_checkbox");
  dlGrid.appendChild(notif.row);
  const webhookEnabled = pgCheckboxRow("pgWebhookEnabled", "web.profile_general.webhook_enabled_checkbox");
  dlGrid.appendChild(webhookEnabled.row);
  const webhookUrlInput = document.createElement("input");
  webhookUrlInput.type = "text";
  webhookUrlInput.id = "pgWebhookUrl";
  webhookUrlInput.placeholder = t("web.profile_general.webhook_url_placeholder");
  webhookUrlInput.dataset.i18nPlaceholder = "web.profile_general.webhook_url_placeholder";
  dlGrid.appendChild(pgFieldRow("web.profile_general.webhook_url_label", webhookUrlInput));
  const launch = pgCheckboxRow("pgLaunchAtStartup", "profile_tab.launch_at_startup_checkbox");
  dlGrid.appendChild(launch.row);
  const updates = pgCheckboxRow("pgCheckForUpdates", "profile_tab.check_for_updates_checkbox");
  dlGrid.appendChild(updates.row);
  const tray = pgCheckboxRow("pgMinimizeToTray", "profile_tab.minimize_to_tray_checkbox");
  dlGrid.appendChild(tray.row);

  const saveBtn = document.createElement("button");
  saveBtn.className = "start-btn";
  saveBtn.id = "pgSaveBtn";
  saveBtn.textContent = t("profile_tab.save_button");
  saveBtn.dataset.i18nKey = "profile_tab.save_button";
  container.appendChild(saveBtn);

  const status = document.createElement("p");
  status.className = "status-line";
  status.id = "pgStatus";
  container.appendChild(status);

  // ---- Apparence ----
  const appearanceHeading = document.createElement("h4");
  appearanceHeading.className = "profile-subheading";
  appearanceHeading.textContent = t("web.profile_general.appearance_heading");
  appearanceHeading.dataset.i18nKey = "web.profile_general.appearance_heading";
  container.appendChild(appearanceHeading);

  const appearanceGrid = document.createElement("div");
  appearanceGrid.className = "form-grid";
  container.appendChild(appearanceGrid);

  const themeSelect = document.createElement("select");
  themeSelect.id = "pgThemeSelect";
  appearanceGrid.appendChild(pgFieldRow("profile_tab.theme_label", themeSelect));

  const appearanceSelect = document.createElement("select");
  appearanceSelect.id = "pgAppearanceSelect";
  appearanceGrid.appendChild(pgFieldRow("profile_tab.appearance_mode_label", appearanceSelect));

  const languageSelect = document.createElement("select");
  languageSelect.id = "pgLanguageSelect";
  appearanceGrid.appendChild(pgFieldRow("profile_tab.language_label", languageSelect));

  // ---- Audio ----
  const audioHeading = document.createElement("h4");
  audioHeading.className = "profile-subheading";
  audioHeading.textContent = t("profile_tab.audio_group");
  audioHeading.dataset.i18nKey = "profile_tab.audio_group";
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
  const volumeRow = pgFieldRow("profile_tab.audio_volume_label", volumeSlider);
  volumeRow.appendChild(volumeValue);
  audioGrid.appendChild(volumeRow);

  const audioNote = document.createElement("p");
  audioNote.className = "field-note";
  audioNote.textContent = t("profile_tab.audio_note");
  audioNote.dataset.i18nKey = "profile_tab.audio_note";
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
      webhookEnabled: webhookEnabled.input.checked,
      webhookUrl: webhookUrlInput.value.trim(),
      launchAtStartup: launch.input.checked,
      checkForUpdates: updates.input.checked,
      minimizeToTray: tray.input.checked,
    };
    bridge.saveSettings(values, (result) => {
      status.textContent = result.ok ? t("web.profile_general.settings_saved") : result.error || "";
    });
  });

  themeSelect.addEventListener("change", () => bridge.setTheme(themeSelect.value));
  appearanceSelect.addEventListener("change", () => bridge.setAppearanceMode(appearanceSelect.value));
  languageSelect.addEventListener("change", () => bridge.setLanguage(languageSelect.value));

  // --value (0%-100%) is how CSS sees the position: themes whose charter
  // draws a filled track paint it up to there (see their tokens.css).
  const syncVolume = () => {
    volumeValue.textContent = `${volumeSlider.value}%`;
    volumeSlider.style.setProperty("--value", `${volumeSlider.value}%`);
  };
  volumeSlider.addEventListener("input", syncVolume);
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
    webhookEnabled.input.checked = values.webhookEnabled;
    webhookUrlInput.value = values.webhookUrl;
    updates.input.checked = values.checkForUpdates;
    tray.input.checked = values.minimizeToTray;
    volumeSlider.value = values.audioVolume;
    syncVolume();

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
