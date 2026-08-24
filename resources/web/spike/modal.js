// Shared modal overlay used by the file-priority/peer-list/speed-graph/
// create-torrent dialogs -- one overlay element reused for all of them
// (only one dialog is ever open at a time, same as the native QDialogs).

let _modalOnClose = null;

function openModal(titleText, contentEl, onClose) {
  let overlay = document.getElementById("modalOverlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.id = "modalOverlay";
    const box = document.createElement("div");
    box.className = "modal-box";
    box.id = "modalBox";
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) closeModal();
    });
  }

  const box = document.getElementById("modalBox");
  box.replaceChildren();
  const title = document.createElement("h3");
  title.textContent = titleText; // safe: DOM property assignment, not HTML parsing
  box.appendChild(title);
  box.appendChild(contentEl);

  overlay.classList.add("active");
  _modalOnClose = onClose || null;
}

function closeModal() {
  const overlay = document.getElementById("modalOverlay");
  if (overlay) overlay.classList.remove("active");
  if (_modalOnClose) {
    const cb = _modalOnClose;
    _modalOnClose = null;
    cb();
  }
}

// Mirrors table_helpers.py's confirm_and_remove(): a 3-way choice (remove
// only / remove + delete files / cancel), used everywhere a torrent/
// subscription can be removed -- never a plain single-click delete.
//
// `impact` is an optional preview of what's about to be removed, gathered by
// the caller (never fetched here -- this function only ever displays data
// the caller already has on hand, e.g. from downloadsRows' cached records):
//   { count, totalSize, numSeeds, numPeers, stateLabel }
// numSeeds/numPeers/stateLabel are only meaningful for a single item (mixing
// peer counts/states across a multi-selection isn't a useful figure), so
// downloadsRemovalImpact() only sets them when exactly one record is removed.
function confirmAndRemove(onRemoveOnly, onRemoveWithFiles, impact) {
  const content = document.createElement("div");
  content.className = "form-grid";

  const message = document.createElement("p");
  message.textContent = impact && impact.count > 1
    ? `Voulez-vous vraiment retirer ces ${impact.count} éléments ?`
    : "Voulez-vous vraiment retirer cet élément ?";
  content.appendChild(message);

  if (impact) {
    const details = document.createElement("p");
    details.className = "field-note";
    const parts = [`Taille totale : ${formatSize(impact.totalSize)}`];
    if (impact.stateLabel) parts.push(`État : ${impact.stateLabel}`);
    if (impact.numSeeds !== undefined) parts.push(`${impact.numSeeds} seeds / ${impact.numPeers} pairs`);
    details.textContent = parts.join(" — "); // safe: DOM property assignment, not HTML parsing
    content.appendChild(details);
  }

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";

  const removeOnlyBtn = document.createElement("button");
  removeOnlyBtn.textContent = "Retirer seulement";
  removeOnlyBtn.addEventListener("click", () => {
    closeModal();
    onRemoveOnly();
  });
  buttonRow.appendChild(removeOnlyBtn);

  const removeWithFilesBtn = document.createElement("button");
  removeWithFilesBtn.textContent = "Retirer et supprimer les fichiers";
  removeWithFilesBtn.addEventListener("click", () => {
    closeModal();
    onRemoveWithFiles();
  });
  buttonRow.appendChild(removeWithFilesBtn);

  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "Annuler";
  cancelBtn.addEventListener("click", () => closeModal());
  buttonRow.appendChild(cancelBtn);

  content.appendChild(buttonRow);
  openModal("Confirmer le retrait", content);
}

// A plain informational message + one "Fermer" button -- the web-spike
// equivalent of QMessageBox.information(), since alert()/confirm()/
// prompt() are avoided throughout this port (they don't compose with a
// frameless embedded view).
function alertModal(titleText, message, buttonLabel, onClose) {
  const content = document.createElement("div");
  content.className = "form-grid";

  const messageEl = document.createElement("p");
  messageEl.textContent = message;
  content.appendChild(messageEl);

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";
  const closeBtn = document.createElement("button");
  closeBtn.textContent = buttonLabel || "Fermer";
  closeBtn.addEventListener("click", () => closeModal());
  buttonRow.appendChild(closeBtn);
  content.appendChild(buttonRow);

  openModal(titleText, content, onClose);
}

// Cancellable countdown for AutoShutdownService -- ticks down once per
// second entirely in JS (no per-second Python->JS call needed), and calls
// the bridge to cancel if "Annuler" is clicked before it reaches zero.
// Mirrors ShutdownCountdownDialog: the actual OS shutdown/hibernate command
// still runs Python-side once AutoShutdownService's own timer elapses --
// this dialog only ever displays/cancels, it never fires the action itself.
let _shutdownCountdownRemaining = 0;
let _shutdownCountdownTimer = null;

function showAutoShutdownCountdown(delaySeconds, action) {
  const actionLabel = action === "hibernate"
    ? "L'ordinateur va se mettre en veille prolongée"
    : "L'ordinateur va s'éteindre";
  _shutdownCountdownRemaining = delaySeconds;

  const content = document.createElement("div");
  content.className = "form-grid";

  const messageEl = document.createElement("p");
  messageEl.textContent = actionLabel;
  content.appendChild(messageEl);

  const countdownEl = document.createElement("p");
  content.appendChild(countdownEl);
  const updateCountdownLabel = () => {
    countdownEl.textContent = `Tous les téléchargements sont terminés. Extinction dans ${_shutdownCountdownRemaining} s.`;
  };
  updateCountdownLabel();

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "Annuler";
  cancelBtn.addEventListener("click", () => {
    window.bridge.autoShutdown.cancelShutdown();
    closeModal();
  });
  buttonRow.appendChild(cancelBtn);
  content.appendChild(buttonRow);

  if (_shutdownCountdownTimer) clearInterval(_shutdownCountdownTimer);
  _shutdownCountdownTimer = setInterval(() => {
    _shutdownCountdownRemaining -= 1;
    if (_shutdownCountdownRemaining <= 0) {
      clearInterval(_shutdownCountdownTimer);
      _shutdownCountdownTimer = null;
      closeModal();
      return;
    }
    updateCountdownLabel();
  }, 1000);

  openModal("Extinction automatique", content, () => {
    if (_shutdownCountdownTimer) {
      clearInterval(_shutdownCountdownTimer);
      _shutdownCountdownTimer = null;
    }
  });
}

// Two-step update flow, mirroring MainWindow._on_update_available/
// _on_installer_verified: first offer to download, then (once the
// installer is downloaded and SHA-256-verified) offer to launch it and
// close the app so the installer can overwrite the locked install dir.
function showUpdateAvailable(version, releaseUrl) {
  const content = document.createElement("div");
  content.className = "form-grid";

  const message = document.createElement("p");
  message.textContent = `Une nouvelle version (${version}) est disponible.`;
  content.appendChild(message);

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";

  const downloadBtn = document.createElement("button");
  downloadBtn.textContent = "Télécharger";
  downloadBtn.addEventListener("click", () => {
    closeModal();
    window.bridge.update.downloadInstaller();
  });
  buttonRow.appendChild(downloadBtn);

  const laterBtn = document.createElement("button");
  laterBtn.textContent = "Plus tard";
  laterBtn.addEventListener("click", () => {
    closeModal();
    window.bridge.update.dismissUpdate(version);
  });
  buttonRow.appendChild(laterBtn);

  content.appendChild(buttonRow);
  openModal("Mise à jour disponible", content);
}

function showInstallerVerified(localPath) {
  const content = document.createElement("div");
  content.className = "form-grid";

  const message = document.createElement("p");
  message.textContent = "La mise à jour a été téléchargée et vérifiée.";
  content.appendChild(message);

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";

  const launchBtn = document.createElement("button");
  launchBtn.textContent = "Installer et redémarrer";
  launchBtn.addEventListener("click", () => {
    closeModal();
    window.bridge.update.launchInstaller(localPath);
  });
  buttonRow.appendChild(launchBtn);

  const laterBtn = document.createElement("button");
  laterBtn.textContent = "Plus tard";
  laterBtn.addEventListener("click", () => {
    closeModal();
    window.bridge.update.discardInstaller(localPath);
  });
  buttonRow.appendChild(laterBtn);

  content.appendChild(buttonRow);
  openModal("Mise à jour vérifiée", content);
}
