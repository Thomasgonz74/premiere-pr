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
    note.textContent =
      "Aucune information de fichiers disponible pour le moment (métadonnées non reçues, ou torrent introuvable).";
    container.appendChild(note);

    const closeRow = document.createElement("div");
    closeRow.className = "modal-close-row";
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Fermer";
    closeBtn.addEventListener("click", () => closeModal());
    closeRow.appendChild(closeBtn);
    container.appendChild(closeRow);
    return;
  }

  if (files.length === 1) {
    const warn = document.createElement("p");
    warn.className = "field-note";
    warn.textContent = "Décocher l'unique fichier exclura le torrent entier.";
    container.appendChild(warn);
  }

  const toolbar = document.createElement("div");
  toolbar.className = "scan-toolbar";
  const checkAllBtn = document.createElement("button");
  checkAllBtn.textContent = "Tout cocher";
  checkAllBtn.addEventListener("click", () => {
    list.querySelectorAll(".fp-check").forEach((c) => (c.checked = true));
  });
  const uncheckAllBtn = document.createElement("button");
  uncheckAllBtn.textContent = "Tout décocher";
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
  saveBtn.textContent = "Enregistrer";
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
  cancelBtn.textContent = "Annuler";
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
  loading.textContent = "Chargement…";
  container.appendChild(loading);

  // titleText is passed to openModal, which assigns it via .textContent
  // (safe even though torrentName is untrusted torrent-file data).
  openModal(`Fichiers — ${torrentName}`, container);

  window.bridge.filePriority.getFiles(infoHash, (files) => {
    fpRenderContent(container, infoHash, files);
  });
}
