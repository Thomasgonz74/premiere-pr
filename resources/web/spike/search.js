// Search page wiring (catalogue idea "recherche de torrents integree").
// Ships with ZERO default sources -- see torrent_search_service.py's own
// docstring on why. The URL-template input only shows an example as a
// placeholder (never a real value) so users see the expected "{query}"
// format without a fake default source being saved. Mirrors rss.js's
// inline add-form + listbox pattern.

let searchSources = []; // [{name, urlTemplate, enabled}]

function searchBuildPage() {
  const root = document.getElementById("searchContainer");

  const sourcesLabel = document.createElement("p");
  sourcesLabel.className = "field-label";
  sourcesLabel.textContent = t("web.search.sources_heading");
  sourcesLabel.dataset.i18nKey = "web.search.sources_heading";
  root.appendChild(sourcesLabel);

  const addGrid = document.createElement("div");
  addGrid.className = "form-grid";

  const nameRow = document.createElement("div");
  nameRow.className = "field-row";
  const nameLabel = document.createElement("label");
  nameLabel.className = "field-label inline";
  nameLabel.textContent = t("web.search.name_label");
  nameLabel.dataset.i18nKey = "web.search.name_label";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.id = "searchSourceNameInput";
  nameInput.placeholder = t("web.search.name_placeholder");
  nameInput.dataset.i18nPlaceholder = "web.search.name_placeholder";
  nameRow.appendChild(nameLabel);
  nameRow.appendChild(nameInput);
  addGrid.appendChild(nameRow);

  const urlRow = document.createElement("div");
  urlRow.className = "field-row";
  const urlLabel = document.createElement("label");
  urlLabel.className = "field-label inline";
  urlLabel.textContent = t("web.search.url_template_label");
  urlLabel.dataset.i18nKey = "web.search.url_template_label";
  const urlInput = document.createElement("input");
  urlInput.type = "text";
  urlInput.id = "searchSourceUrlInput";
  urlInput.placeholder = t("web.search.url_template_placeholder");
  urlInput.dataset.i18nPlaceholder = "web.search.url_template_placeholder";
  urlRow.appendChild(urlLabel);
  urlRow.appendChild(urlInput);
  addGrid.appendChild(urlRow);

  const enabledRow = document.createElement("div");
  enabledRow.className = "field-row";
  const enabledCheck = document.createElement("input");
  enabledCheck.type = "checkbox";
  enabledCheck.id = "searchSourceEnabledInput";
  enabledCheck.checked = true;
  const enabledLabel = document.createElement("label");
  enabledLabel.className = "field-label inline";
  enabledLabel.textContent = t("web.search.enabled_label");
  enabledLabel.dataset.i18nKey = "web.search.enabled_label";
  enabledLabel.htmlFor = "searchSourceEnabledInput";
  enabledRow.appendChild(enabledCheck);
  enabledRow.appendChild(enabledLabel);
  addGrid.appendChild(enabledRow);

  const addBtnRow = document.createElement("div");
  addBtnRow.className = "field-row";
  const addBtn = document.createElement("button");
  addBtn.className = "start-btn";
  addBtn.id = "searchSourceAddBtn";
  addBtn.textContent = t("web.search.add_source_button");
  addBtn.dataset.i18nKey = "web.search.add_source_button";
  addBtnRow.appendChild(addBtn);
  addGrid.appendChild(addBtnRow);

  root.appendChild(addGrid);

  const sourceList = document.createElement("div");
  sourceList.className = "listbox";
  sourceList.id = "searchSourceList";
  root.appendChild(sourceList);

  const searchLabel = document.createElement("p");
  searchLabel.className = "field-label";
  searchLabel.textContent = t("web.search.heading");
  searchLabel.dataset.i18nKey = "web.search.heading";
  root.appendChild(searchLabel);

  const searchRow = document.createElement("div");
  searchRow.className = "field-row";
  const queryInput = document.createElement("input");
  queryInput.type = "text";
  queryInput.className = "search-input";
  queryInput.id = "searchQueryInput";
  queryInput.placeholder = t("web.search.query_placeholder");
  queryInput.dataset.i18nPlaceholder = "web.search.query_placeholder";
  searchRow.appendChild(queryInput);
  const searchBtn = document.createElement("button");
  searchBtn.className = "start-btn";
  searchBtn.id = "searchGoBtn";
  searchBtn.textContent = t("web.search.go_button");
  searchBtn.dataset.i18nKey = "web.search.go_button";
  searchRow.appendChild(searchBtn);
  root.appendChild(searchRow);

  const searchStatus = document.createElement("p");
  searchStatus.className = "status-line";
  searchStatus.id = "searchStatus";
  root.appendChild(searchStatus);

  const resultsList = document.createElement("div");
  resultsList.className = "listbox";
  resultsList.id = "searchResultsList";
  root.appendChild(resultsList);
}

function searchRenderSourceList() {
  const list = document.getElementById("searchSourceList");
  list.replaceChildren();

  if (!searchSources.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = t("web.search.no_sources");
    list.appendChild(note);
    return;
  }

  searchSources.forEach((source) => {
    const row = document.createElement("div");
    row.className = "row";

    const nameEl = document.createElement("span");
    nameEl.className = "row-name";
    nameEl.textContent = source.name;
    nameEl.title = source.urlTemplate;
    row.appendChild(nameEl);

    const enabledCheck = document.createElement("input");
    enabledCheck.type = "checkbox";
    enabledCheck.checked = source.enabled;
    enabledCheck.addEventListener("change", () => {
      window.bridge.search.saveSource(source.name, source.urlTemplate, enabledCheck.checked);
      source.enabled = enabledCheck.checked;
    });
    row.appendChild(enabledCheck);

    const actions = document.createElement("div");
    actions.className = "row-actions";
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", () => {
      window.bridge.search.deleteSource(source.name);
      searchSources = searchSources.filter((s) => s.name !== source.name);
      searchRenderSourceList();
    });
    actions.appendChild(removeBtn);
    row.appendChild(actions);

    list.appendChild(row);
  });
}

function searchReloadSources() {
  window.bridge.search.listSources((sources) => {
    searchSources = sources;
    searchRenderSourceList();
  });
}

function searchRenderResults(results) {
  const list = document.getElementById("searchResultsList");
  list.replaceChildren();

  if (!results.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = t("web.search.no_results");
    list.appendChild(note);
    return;
  }

  results.forEach((result) => {
    const row = document.createElement("div");
    row.className = "row";

    const titleEl = document.createElement("span");
    titleEl.className = "row-name";
    titleEl.textContent = result.title;
    titleEl.title = `${result.title} — ${result.source}`;
    row.appendChild(titleEl);

    const sourceEl = document.createElement("span");
    sourceEl.textContent = result.source;
    row.appendChild(sourceEl);

    const actions = document.createElement("div");
    actions.className = "row-actions";
    const addBtn = document.createElement("button");
    addBtn.textContent = t("common.add");
    addBtn.addEventListener("click", () => {
      if (result.link.startsWith("magnet:")) {
        switchToTab("add");
        window.bridge.add.analyzeMagnet(result.link);
      } else {
        window.bridge.dialogs.openExternalUrl(result.link);
      }
    });
    actions.appendChild(addBtn);
    row.appendChild(actions);

    list.appendChild(row);
  });
}

function wireSearchPage() {
  searchBuildPage();
  const searchBridge = window.bridge.search;

  document.getElementById("searchSourceAddBtn").addEventListener("click", () => {
    const name = document.getElementById("searchSourceNameInput").value.trim();
    const urlTemplate = document.getElementById("searchSourceUrlInput").value.trim();
    const enabled = document.getElementById("searchSourceEnabledInput").checked;
    if (!name || !urlTemplate) return;
    searchBridge.saveSource(name, urlTemplate, enabled);
    document.getElementById("searchSourceNameInput").value = "";
    document.getElementById("searchSourceUrlInput").value = "";
    searchReloadSources();
  });

  document.getElementById("searchGoBtn").addEventListener("click", () => {
    const query = document.getElementById("searchQueryInput").value.trim();
    if (!query) return;
    document.getElementById("searchStatus").textContent = t("web.search.searching_status");
    searchBridge.search(query);
  });

  searchBridge.resultsReady.connect((results) => {
    document.getElementById("searchStatus").textContent = "";
    searchRenderResults(results);
  });

  searchReloadSources();
}
