// Torrent-creation dialog -- mirrors CreateTorrentDialog (native) exactly:
// pick a source file/folder via the native pickers (DialogBridge), build a
// freestanding tracker list in memory, then hand everything to
// CreateTorrentBridge.createTorrent() which writes the .torrent file.
// Transient dialog, no async initial load -- built and opened synchronously.

function openCreateTorrentDialog() {
  const dialogs = window.bridge.dialogs;
  const createTorrentBridge = window.bridge.createTorrent;
  let sourcePath = "";

  const content = document.createElement("div");
  content.className = "form-grid";

  // ---- Source ----
  const sourceLabel = document.createElement("p");
  sourceLabel.className = "field-note";
  content.appendChild(sourceLabel);

  const sourceRow = document.createElement("div");
  sourceRow.className = "field-row";
  const chooseFileBtn = document.createElement("button");
  chooseFileBtn.textContent = t("web.create_torrent.choose_file_button");
  const chooseFolderBtn = document.createElement("button");
  chooseFolderBtn.textContent = t("web.create_torrent.choose_folder_button");
  sourceRow.appendChild(chooseFileBtn);
  sourceRow.appendChild(chooseFolderBtn);
  content.appendChild(sourceRow);

  chooseFileBtn.addEventListener("click", () => {
    dialogs.browseOpenFile(t("web.create_torrent.all_files_filter"), (path) => {
      if (!path) return;
      sourcePath = path;
      sourceLabel.textContent = path;
    });
  });
  chooseFolderBtn.addEventListener("click", () => {
    dialogs.browseFolder("", (path) => {
      if (!path) return;
      sourcePath = path;
      sourceLabel.textContent = path;
    });
  });

  // ---- Trackers ----
  const trackersLabel = document.createElement("p");
  trackersLabel.className = "field-label";
  trackersLabel.textContent = t("create_torrent.trackers_group");
  content.appendChild(trackersLabel);

  const trackersList = document.createElement("ul");
  trackersList.className = "listbox";
  content.appendChild(trackersList);

  const trackerAddRow = document.createElement("div");
  trackerAddRow.className = "field-row";
  const trackerInput = document.createElement("input");
  trackerInput.type = "text";
  trackerInput.placeholder = "http://tracker.example.com/announce";
  const addTrackerBtn = document.createElement("button");
  addTrackerBtn.textContent = t("common.add");
  trackerAddRow.appendChild(trackerInput);
  trackerAddRow.appendChild(addTrackerBtn);
  content.appendChild(trackerAddRow);

  addTrackerBtn.addEventListener("click", () => {
    const url = trackerInput.value.trim();
    if (!url) return;
    const li = document.createElement("li");
    li.textContent = url;
    li.title = t("web.create_torrent.click_to_remove");
    li.style.cursor = "pointer";
    li.addEventListener("click", () => li.remove());
    trackersList.appendChild(li);
    trackerInput.value = "";
  });

  // ---- Private + comment ----
  const privateRow = document.createElement("label");
  privateRow.className = "field-row";
  const privateCheckbox = document.createElement("input");
  privateCheckbox.type = "checkbox";
  const privateText = document.createElement("span");
  privateText.textContent = t("create_torrent.private_checkbox");
  privateRow.appendChild(privateCheckbox);
  privateRow.appendChild(privateText);
  content.appendChild(privateRow);

  const commentRow = document.createElement("div");
  commentRow.className = "field-row";
  const commentLabel = document.createElement("span");
  commentLabel.className = "field-label inline";
  commentLabel.textContent = t("web.create_torrent.comment_label");
  const commentInput = document.createElement("input");
  commentInput.type = "text";
  commentRow.appendChild(commentLabel);
  commentRow.appendChild(commentInput);
  content.appendChild(commentRow);

  // ---- Status ----
  const status = document.createElement("p");
  status.className = "status-line";
  content.appendChild(status);

  // ---- Buttons ----
  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";
  const createBtn = document.createElement("button");
  createBtn.textContent = t("web.create_torrent.create_button");
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = t("common.cancel");
  buttonRow.appendChild(createBtn);
  buttonRow.appendChild(cancelBtn);
  content.appendChild(buttonRow);

  cancelBtn.addEventListener("click", () => closeModal());

  createBtn.addEventListener("click", () => {
    if (!sourcePath) {
      status.textContent = t("web.create_torrent.no_source_message");
      return;
    }
    const defaultName = sourcePath.split(/[\\/]/).pop() + ".torrent";
    dialogs.browseSaveFile(defaultName, "Torrent (*.torrent)", (outputPath) => {
      if (!outputPath) return;
      const trackerList = [...trackersList.querySelectorAll("li")].map((li) => li.textContent);
      createTorrentBridge.createTorrent(
        sourcePath,
        outputPath,
        trackerList,
        privateCheckbox.checked,
        commentInput.value.trim(),
        (result) => {
          if (result.ok) {
            status.textContent = t("web.create_torrent.created", { path: outputPath });
            closeModal();
          } else {
            status.textContent = result.error;
          }
        }
      );
    });
  });

  openModal(t("create_torrent.window_title"), content);
}
