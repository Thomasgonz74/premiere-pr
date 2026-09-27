// Profile / Security-Data page wiring. Mirrors profile_sections.py's
// SecuritySection + DiagnosticsSection + ConfigImportExportSection.

function profileSecurityBuildSection(key) {
  const section = document.createElement("fieldset");
  section.className = "profile-subsection";
  const legend = document.createElement("legend");
  legend.textContent = t(key);
  legend.dataset.i18nKey = key;
  section.appendChild(legend);
  return section;
}

function profileSecurityNote(key) {
  const note = document.createElement("p");
  note.className = "field-note";
  note.textContent = t(key);
  note.dataset.i18nKey = key;
  return note;
}

function wireProfileSecurity() {
  const bridge = window.bridge.profileSecurity;
  const dialogs = window.bridge.dialogs;
  const container = document.getElementById("profileSecurityContainer");

  const status = document.createElement("p");
  status.className = "status-line";
  status.id = "profileSecurityStatus";

  // -- Sécurité ----------------------------------------------------------

  const securitySection = profileSecurityBuildSection("profile_tab.security_group");
  const defenderBtn = document.createElement("button");
  defenderBtn.textContent = t("web.profile_security.open_defender_button");
  defenderBtn.dataset.i18nKey = "web.profile_security.open_defender_button";
  defenderBtn.addEventListener("click", () => bridge.openDefender());
  securitySection.appendChild(defenderBtn);
  securitySection.appendChild(profileSecurityNote("web.profile_security.defender_note"));

  const scanRow = document.createElement("div");
  scanRow.className = "field-row";
  const scanCheck = document.createElement("input");
  scanCheck.type = "checkbox";
  scanCheck.id = "profileSecurityScanCheck";
  const scanLabel = document.createElement("label");
  scanLabel.className = "field-label inline";
  scanLabel.htmlFor = "profileSecurityScanCheck";
  scanLabel.textContent = t("web.profile_security.scan_checkbox");
  scanLabel.dataset.i18nKey = "web.profile_security.scan_checkbox";
  scanRow.appendChild(scanCheck);
  scanRow.appendChild(scanLabel);
  securitySection.appendChild(scanRow);

  const securitySaveBtn = document.createElement("button");
  securitySaveBtn.className = "start-btn";
  securitySaveBtn.textContent = t("profile_tab.save_button");
  securitySaveBtn.dataset.i18nKey = "profile_tab.save_button";
  securitySaveBtn.addEventListener("click", () => {
    bridge.saveSettings({ scanCompletedFilesWithDefender: scanCheck.checked }, (result) => {
      status.textContent = result.ok
        ? t("web.profile_security.settings_saved")
        : result.error || t("web.profile_security.save_failed");
    });
  });
  securitySection.appendChild(securitySaveBtn);

  bridge.getSettings((values) => {
    scanCheck.checked = !!values.scanCompletedFilesWithDefender;
  });

  // -- Diagnostics ---------------------------------------------------------

  const diagnosticsSection = profileSecurityBuildSection("web.profile_security.diagnostics_heading");
  const openLogsBtn = document.createElement("button");
  openLogsBtn.textContent = t("web.profile_security.open_logs_button");
  openLogsBtn.dataset.i18nKey = "web.profile_security.open_logs_button";
  openLogsBtn.addEventListener("click", () => bridge.openLogsFolder());
  diagnosticsSection.appendChild(openLogsBtn);

  const copyLogBtn = document.createElement("button");
  copyLogBtn.textContent = t("web.profile_security.copy_log_button");
  copyLogBtn.dataset.i18nKey = "web.profile_security.copy_log_button";
  copyLogBtn.addEventListener("click", () => {
    // The bridge puts the log on the clipboard itself (no 5 MB round trip).
    bridge.copyLogToClipboard((result) => {
      if (result.ok) status.textContent = t("web.profile_security.log_copied");
      else if (result.clipboardError) status.textContent = t("web.profile_security.clipboard_error");
      else status.textContent = t("web.profile_security.no_log");
    });
  });
  diagnosticsSection.appendChild(copyLogBtn);
  diagnosticsSection.appendChild(profileSecurityNote("web.profile_security.copy_log_note"));

  // -- Configuration ---------------------------------------------------------

  const configSection = profileSecurityBuildSection("profile_tab.config_group");
  const configRow = document.createElement("div");
  configRow.className = "field-row";

  const exportBtn = document.createElement("button");
  exportBtn.textContent = t("web.profile_security.export_button");
  exportBtn.dataset.i18nKey = "web.profile_security.export_button";
  exportBtn.addEventListener("click", () => {
    dialogs.browseSaveFile("torrent2000_config.json", "JSON (*.json)", (path) => {
      if (!path) return;
      bridge.exportConfig(path, (result) => {
        status.textContent = result.ok
          ? t("web.profile_security.export_success", { path })
          : result.error || t("web.profile_security.export_failed");
      });
    });
  });
  configRow.appendChild(exportBtn);

  const importBtn = document.createElement("button");
  importBtn.textContent = t("web.profile_security.import_button");
  importBtn.dataset.i18nKey = "web.profile_security.import_button";
  importBtn.addEventListener("click", () => {
    dialogs.browseOpenFile("JSON (*.json)", (path) => {
      if (!path) return;
      if (!confirm(t("web.profile_security.import_confirm"))) {
        return;
      }
      bridge.importConfig(path, (result) => {
        status.textContent = result.ok
          ? t("profile_tab.import_success_message")
          : result.error || t("web.profile_security.import_failed");
      });
    });
  });
  configRow.appendChild(importBtn);

  configSection.appendChild(configRow);
  configSection.appendChild(profileSecurityNote("web.profile_security.export_password_note"));

  container.appendChild(securitySection);
  container.appendChild(diagnosticsSection);
  container.appendChild(configSection);
  container.appendChild(status);
}
