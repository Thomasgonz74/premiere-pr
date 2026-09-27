// Shared modal overlay used by the file-priority/peer-list/speed-graph/
// create-torrent dialogs -- one overlay element reused for all of them
// (only one dialog is ever open at a time, same as the native QDialogs).

let _modalOnClose = null;

function openModal(titleText, contentEl, onClose) {
  // A dialog replaced by this one is closed too: the polling dialogs only
  // stop their timer in onClose, so dropping it leaked the poll for good.
  if (_modalOnClose) {
    const cb = _modalOnClose;
    _modalOnClose = null;
    cb();
  }
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
    ? t("web.modal.remove_confirm_plural", { count: impact.count })
    : t("common.remove_confirm_message");
  content.appendChild(message);

  if (impact) {
    const details = document.createElement("p");
    details.className = "field-note";
    const parts = [t("web.modal.total_size", { size: formatSize(impact.totalSize) })];
    if (impact.stateLabel) parts.push(t("web.modal.state_label", { state: impact.stateLabel }));
    if (impact.numSeeds !== undefined) parts.push(t("web.modal.seeds_peers", { seeds: impact.numSeeds, peers: impact.numPeers }));
    details.textContent = parts.join(" — "); // safe: DOM property assignment, not HTML parsing
    content.appendChild(details);
  }

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";

  const removeOnlyBtn = document.createElement("button");
  removeOnlyBtn.textContent = t("common.remove_only_button");
  removeOnlyBtn.addEventListener("click", () => {
    closeModal();
    onRemoveOnly();
  });
  buttonRow.appendChild(removeOnlyBtn);

  const removeWithFilesBtn = document.createElement("button");
  removeWithFilesBtn.textContent = t("common.remove_with_files_button");
  removeWithFilesBtn.addEventListener("click", () => {
    closeModal();
    onRemoveWithFiles();
  });
  buttonRow.appendChild(removeWithFilesBtn);

  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = t("common.cancel");
  cancelBtn.addEventListener("click", () => closeModal());
  buttonRow.appendChild(cancelBtn);

  content.appendChild(buttonRow);
  openModal(t("common.remove_confirm_title"), content);
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
  closeBtn.textContent = buttonLabel || t("titlebar.close");
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
    ? t("shutdown_dialog.action_hibernate")
    : t("shutdown_dialog.action_shutdown");
  _shutdownCountdownRemaining = delaySeconds;

  const content = document.createElement("div");
  content.className = "form-grid";

  const messageEl = document.createElement("p");
  messageEl.textContent = actionLabel;
  content.appendChild(messageEl);

  const countdownEl = document.createElement("p");
  content.appendChild(countdownEl);
  const updateCountdownLabel = () => {
    countdownEl.textContent = t("shutdown_dialog.countdown", { seconds: _shutdownCountdownRemaining });
  };
  updateCountdownLabel();

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = t("common.cancel");
  cancelBtn.addEventListener("click", () => {
    window.bridge.autoShutdown.cancelShutdown();
    closeModal();
  });
  buttonRow.appendChild(cancelBtn);
  content.appendChild(buttonRow);

  // Timer created only after openModal(): opening runs the previous
  // dialog's onClose, which for an earlier countdown clears
  // _shutdownCountdownTimer -- it would kill a timer created before.
  openModal(t("shutdown_dialog.window_title"), content, () => {
    if (_shutdownCountdownTimer) {
      clearInterval(_shutdownCountdownTimer);
      _shutdownCountdownTimer = null;
    }
  });

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
}

// Two-step update flow, mirroring MainWindow._on_update_available/
// _on_installer_verified: first offer to download, then (once the
// installer is downloaded and SHA-256-verified) offer to launch it and
// close the app so the installer can overwrite the locked install dir.
function showUpdateAvailable(version, releaseUrl) {
  const content = document.createElement("div");
  content.className = "form-grid";

  const message = document.createElement("p");
  message.textContent = t("web.modal.update_available_message", { version });
  content.appendChild(message);

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";

  const downloadBtn = document.createElement("button");
  downloadBtn.textContent = t("update.download_button");
  downloadBtn.addEventListener("click", () => {
    closeModal();
    window.bridge.update.downloadInstaller();
  });
  buttonRow.appendChild(downloadBtn);

  const laterBtn = document.createElement("button");
  laterBtn.textContent = t("update.later_button");
  laterBtn.addEventListener("click", () => {
    closeModal();
    window.bridge.update.dismissUpdate(version);
  });
  buttonRow.appendChild(laterBtn);

  content.appendChild(buttonRow);
  openModal(t("update.title"), content);
}

function showInstallerVerified(localPath) {
  const content = document.createElement("div");
  content.className = "form-grid";

  const message = document.createElement("p");
  message.textContent = t("web.modal.installer_verified_message");
  content.appendChild(message);

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";

  const launchBtn = document.createElement("button");
  launchBtn.textContent = t("web.modal.launch_and_restart_button");
  launchBtn.addEventListener("click", () => {
    closeModal();
    window.bridge.update.launchInstaller(localPath);
  });
  buttonRow.appendChild(launchBtn);

  const laterBtn = document.createElement("button");
  laterBtn.textContent = t("update.later_button");
  laterBtn.addEventListener("click", () => {
    closeModal();
    window.bridge.update.discardInstaller(localPath);
  });
  buttonRow.appendChild(laterBtn);

  content.appendChild(buttonRow);
  openModal(t("web.modal.installer_verified_title"), content);
}
