// Profile / Security-Data page wiring. Mirrors profile_sections.py's
// SecuritySection + DiagnosticsSection + ConfigImportExportSection.

function profileSecurityBuildSection(title) {
  const section = document.createElement("fieldset");
  section.className = "profile-subsection";
  const legend = document.createElement("legend");
  legend.textContent = title;
  section.appendChild(legend);
  return section;
}

function profileSecurityNote(text) {
  const note = document.createElement("p");
  note.className = "field-note";
  note.textContent = text;
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

  const securitySection = profileSecurityBuildSection("Sécurité");
  const defenderBtn = document.createElement("button");
  defenderBtn.textContent = "Ouvrir Windows Defender";
  defenderBtn.addEventListener("click", () => bridge.openDefender());
  securitySection.appendChild(defenderBtn);
  securitySection.appendChild(
    profileSecurityNote("Ouvre la page des exclusions de Windows Security — ajoutez-en une vous-même si besoin.")
  );

  const scanRow = document.createElement("div");
  scanRow.className = "field-row";
  const scanCheck = document.createElement("input");
  scanCheck.type = "checkbox";
  scanCheck.id = "profileSecurityScanCheck";
  const scanLabel = document.createElement("label");
  scanLabel.className = "field-label inline";
  scanLabel.htmlFor = "profileSecurityScanCheck";
  scanLabel.textContent = "Analyser les fichiers téléchargés avec Windows Defender";
  scanRow.appendChild(scanCheck);
  scanRow.appendChild(scanLabel);
  securitySection.appendChild(scanRow);

  const securitySaveBtn = document.createElement("button");
  securitySaveBtn.className = "start-btn";
  securitySaveBtn.textContent = "Enregistrer";
  securitySaveBtn.addEventListener("click", () => {
    bridge.saveSettings({ scanCompletedFilesWithDefender: scanCheck.checked }, (result) => {
      status.textContent = result.ok ? "Paramètres de sécurité enregistrés." : result.error || "Échec de l'enregistrement.";
    });
  });
  securitySection.appendChild(securitySaveBtn);

  bridge.getSettings((values) => {
    scanCheck.checked = !!values.scanCompletedFilesWithDefender;
  });

  // -- Diagnostics ---------------------------------------------------------

  const diagnosticsSection = profileSecurityBuildSection("Diagnostics");
  const openLogsBtn = document.createElement("button");
  openLogsBtn.textContent = "Ouvrir le dossier des journaux";
  openLogsBtn.addEventListener("click", () => bridge.openLogsFolder());
  diagnosticsSection.appendChild(openLogsBtn);

  const copyLogBtn = document.createElement("button");
  copyLogBtn.textContent = "Copier le journal";
  copyLogBtn.addEventListener("click", () => {
    bridge.copyLogToClipboard((result) => {
      if (!result.ok) {
        status.textContent = "Aucun journal disponible.";
        return;
      }
      navigator.clipboard
        .writeText(result.text)
        .then(() => (status.textContent = "Journal copié dans le presse-papiers."))
        .catch(() => (status.textContent = "Impossible d'accéder au presse-papiers."));
    });
  });
  diagnosticsSection.appendChild(copyLogBtn);
  diagnosticsSection.appendChild(
    profileSecurityNote("Copiez le journal pour le joindre à un rapport de bug.")
  );

  // -- Configuration ---------------------------------------------------------

  const configSection = profileSecurityBuildSection("Configuration");
  const configRow = document.createElement("div");
  configRow.className = "field-row";

  const exportBtn = document.createElement("button");
  exportBtn.textContent = "Exporter…";
  exportBtn.addEventListener("click", () => {
    dialogs.browseSaveFile("torrent2000_config.json", "JSON (*.json)", (path) => {
      if (!path) return;
      bridge.exportConfig(path, (result) => {
        status.textContent = result.ok
          ? `Configuration exportée vers ${path}.`
          : result.error || "Échec de l'export.";
      });
    });
  });
  configRow.appendChild(exportBtn);

  const importBtn = document.createElement("button");
  importBtn.textContent = "Importer…";
  importBtn.addEventListener("click", () => {
    dialogs.browseOpenFile("JSON (*.json)", (path) => {
      if (!path) return;
      if (!confirm("Remplacer la configuration actuelle par le fichier importé ? Un redémarrage sera nécessaire.")) {
        return;
      }
      bridge.importConfig(path, (result) => {
        status.textContent = result.ok
          ? "Configuration importée. Redémarrez Torrent 2000 pour l'appliquer."
          : result.error || "Échec de l'import.";
      });
    });
  });
  configRow.appendChild(importBtn);

  configSection.appendChild(configRow);
  configSection.appendChild(
    profileSecurityNote("Le mot de passe du proxy n'est jamais inclus dans l'export.")
  );

  container.appendChild(securitySection);
  container.appendChild(diagnosticsSection);
  container.appendChild(configSection);
  container.appendChild(status);
}
