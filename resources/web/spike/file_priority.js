// Post-start file inclusion/exclusion editor -- mirrors native
// FilePriorityDialog. Every file starts checked (no way to read back
// current per-file priority from a running torrent); Enregistrer sends the
// full set of now-unchecked indices, which set_file_priorities() applies as
// a full replacement (re-checked files are correctly restored too).

function fpBuildRow(file) {
  const row = document.createElement("div");
  row.className = "field-row";
  row.dataset.index = String(file.index);

  const check = document.createElement("input");
  check.type = "checkbox";
  check.checked = true;
  check.className = "fp-check";
  row.appendChild(check);

  const path = document.createElement("span");
  path.className = "scan-path";
  path.style.flex = "1";
  path.textContent = file.path; // safe: .textContent -- path comes from torrent metadata, untrusted
  path.title = file.path;
  row.appendChild(path);

  const size = document.createElement("span");
  size.className = "scan-size";
  size.style.width = "90px";
  size.textContent = formatSize(file.size);
  row.appendChild(size);

  return row;
}

function fpRenderContent(container, infoHash, files) {
  container.replaceChildren();

  if (files.length === 0) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = t("web.file_priority.no_metadata_message");
    container.appendChild(note);

    const closeRow = document.createElement("div");
    closeRow.className = "modal-close-row";
    const closeBtn = document.createElement("button");
    closeBtn.textContent = t("titlebar.close");
    closeBtn.addEventListener("click", () => closeModal());
    closeRow.appendChild(closeBtn);
    container.appendChild(closeRow);
    return;
  }

  if (files.length === 1) {
    const warn = document.createElement("p");
    warn.className = "field-note";
    warn.textContent = t("web.file_priority.single_file_message");
    container.appendChild(warn);
  }

  const toolbar = document.createElement("div");
  toolbar.className = "scan-toolbar";
  const checkAllBtn = document.createElement("button");
  checkAllBtn.textContent = t("file_priority_dialog.check_all");
  checkAllBtn.addEventListener("click", () => {
    list.querySelectorAll(".fp-check").forEach((c) => (c.checked = true));
  });
  const uncheckAllBtn = document.createElement("button");
  uncheckAllBtn.textContent = t("file_priority_dialog.uncheck_all");
  uncheckAllBtn.addEventListener("click", () => {
    list.querySelectorAll(".fp-check").forEach((c) => (c.checked = false));
  });
  toolbar.appendChild(checkAllBtn);
  toolbar.appendChild(uncheckAllBtn);
  container.appendChild(toolbar);

  const list = document.createElement("div");
  list.className = "listbox";
  files.forEach((file) => list.appendChild(fpBuildRow(file)));
  container.appendChild(list);

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";
  const saveBtn = document.createElement("button");
  saveBtn.textContent = t("file_priority_dialog.save_button");
  saveBtn.addEventListener("click", () => {
    const excluded = [];
    list.querySelectorAll(".field-row").forEach((row) => {
      if (!row.querySelector(".fp-check").checked) {
        excluded.push(parseInt(row.dataset.index, 10));
      }
    });
    window.bridge.filePriority.saveFilePriorities(infoHash, excluded);
    closeModal();
  });
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = t("common.cancel");
  cancelBtn.addEventListener("click", () => closeModal());
  buttonRow.appendChild(saveBtn);
  buttonRow.appendChild(cancelBtn);
  container.appendChild(buttonRow);
}

function openFilePriorityDialog(infoHash, torrentName) {
  const container = document.createElement("div");
  container.className = "form-grid";
  const loading = document.createElement("p");
  loading.className = "status-line";
  loading.textContent = t("web.file_priority.loading");
  container.appendChild(loading);

  // titleText is passed to openModal, which assigns it via .textContent
  // (safe even though torrentName is untrusted torrent-file data).
  openModal(t("web.file_priority.dialog_title", { name: torrentName }), container);

  window.bridge.filePriority.getFiles(infoHash, (files) => {
    fpRenderContent(container, infoHash, files);
  });
}
