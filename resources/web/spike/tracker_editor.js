// Per-torrent tracker list editor. Mirrors TrackerEditorWidget: a list of
// trackers (URL / tier / last error / Retirer button) plus an add-tracker
// input + Ajouter button. No incremental patching -- every add/remove just
// calls renderTrackerEditor again, same as the native widget's refresh().
//
// Called by the details panel whenever the selected torrent changes:
//   renderTrackerEditor(containerEl, infoHash)

function renderTrackerEditor(containerEl, infoHash) {
  containerEl.replaceChildren();

  const header = document.createElement("div");
  header.className = "row";
  header.style.fontWeight = "bold";
  ["URL", "Niveau", "Dernière erreur", "Action"].forEach((text) => {
    const cell = document.createElement("div");
    cell.textContent = text;
    header.appendChild(cell);
  });
  containerEl.appendChild(header);

  const list = document.createElement("div");
  list.className = "listbox";
  containerEl.appendChild(list);

  const addRow = document.createElement("div");
  addRow.className = "field-row";
  const urlInput = document.createElement("input");
  urlInput.type = "text";
  urlInput.placeholder = "http://tracker.example.com/announce";
  addRow.appendChild(urlInput);
  const addBtn = document.createElement("button");
  addBtn.textContent = "Ajouter";
  addBtn.addEventListener("click", () => {
    const url = urlInput.value.trim();
    if (!url) return;
    window.bridge.trackerEditor.addTracker(infoHash, url);
    urlInput.value = "";
    renderTrackerEditor(containerEl, infoHash);
  });
  addRow.appendChild(addBtn);
  containerEl.appendChild(addRow);

  window.bridge.trackerEditor.getTrackers(infoHash, (trackers) => {
    list.replaceChildren();

    if (trackers.length === 0) {
      const note = document.createElement("p");
      note.className = "empty-note";
      note.textContent = "Aucun tracker.";
      list.appendChild(note);
      return;
    }

    trackers.forEach((tracker) => {
      const row = document.createElement("div");
      row.className = "row";

      const urlEl = document.createElement("span");
      urlEl.className = "row-name";
      urlEl.textContent = tracker.url; // untrusted: tracker data (network-supplied), .textContent only
      urlEl.title = tracker.url;
      row.appendChild(urlEl);

      const tierEl = document.createElement("span");
      tierEl.textContent = String(tracker.tier);
      row.appendChild(tierEl);

      const errorEl = document.createElement("span");
      errorEl.textContent = tracker.lastError; // untrusted: tracker data, .textContent only
      errorEl.title = tracker.lastError;
      row.appendChild(errorEl);

      const actions = document.createElement("div");
      actions.className = "row-actions";
      const removeBtn = document.createElement("button");
      removeBtn.textContent = "Retirer";
      removeBtn.addEventListener("click", () => {
        window.bridge.trackerEditor.removeTracker(infoHash, tracker.url);
        renderTrackerEditor(containerEl, infoHash);
      });
      actions.appendChild(removeBtn);
      row.appendChild(actions);

      list.appendChild(row);
    });
  });
}
