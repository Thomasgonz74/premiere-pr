// RSS page wiring. Mirrors RssTab: subscriptions are re-fetched from the
// server after every add/remove (listFeeds()), the enabled checkbox and
// remove button write straight through to the bridge (live-apply, no Save
// button), and the log panel is purely client-side (appends on the
// itemsFound/feedCheckFailed pushes, capped at MAX_LOG_ENTRIES, newest first
// -- same behavior as RssTab's QListWidget insertItem(0, ...)).

const RSS_MAX_LOG_ENTRIES = 200;

let rssFeeds = []; // [{url, filterKeyword, enabled}]
let rssFilterText = "";

function rssBuildPage() {
  const root = document.getElementById("rssContainer");

  const topRow = document.createElement("div");
  topRow.className = "field-row";
  const label = document.createElement("span");
  label.className = "field-label";
  label.textContent = "Abonnements";
  topRow.appendChild(label);
  const spacer = document.createElement("span");
  spacer.style.flex = "1";
  topRow.appendChild(spacer);
  const checkNowBtn = document.createElement("button");
  checkNowBtn.className = "start-btn";
  checkNowBtn.id = "rssCheckNowBtn";
  checkNowBtn.textContent = "Vérifier maintenant";
  topRow.appendChild(checkNowBtn);
  root.appendChild(topRow);

  const addGrid = document.createElement("div");
  addGrid.className = "form-grid";

  const urlRow = document.createElement("div");
  urlRow.className = "field-row";
  const urlLabel = document.createElement("label");
  urlLabel.className = "field-label inline";
  urlLabel.textContent = "URL du flux";
  const urlInput = document.createElement("input");
  urlInput.type = "text";
  urlInput.id = "rssUrlInput";
  urlInput.placeholder = "https://exemple.com/rss";
  urlRow.appendChild(urlLabel);
  urlRow.appendChild(urlInput);
  addGrid.appendChild(urlRow);

  const keywordRow = document.createElement("div");
  keywordRow.className = "field-row";
  const keywordLabel = document.createElement("label");
  keywordLabel.className = "field-label inline";
  keywordLabel.textContent = "Mot-clé";
  const keywordInput = document.createElement("input");
  keywordInput.type = "text";
  keywordInput.id = "rssKeywordInput";
  keywordInput.placeholder = "Optionnel — filtre les titres";
  keywordRow.appendChild(keywordLabel);
  keywordRow.appendChild(keywordInput);
  addGrid.appendChild(keywordRow);

  const addBtnRow = document.createElement("div");
  addBtnRow.className = "field-row";
  const addBtn = document.createElement("button");
  addBtn.className = "start-btn";
  addBtn.id = "rssAddBtn";
  addBtn.textContent = "Ajouter";
  addBtnRow.appendChild(addBtn);
  addGrid.appendChild(addBtnRow);

  const addStatus = document.createElement("p");
  addStatus.className = "status-line";
  addStatus.id = "rssAddStatus";
  addGrid.appendChild(addStatus);

  root.appendChild(addGrid);

  const searchInput = document.createElement("input");
  searchInput.type = "text";
  searchInput.className = "search-input";
  searchInput.id = "rssSearchInput";
  searchInput.placeholder = "Rechercher…";
  root.appendChild(searchInput);

  const feedList = document.createElement("div");
  feedList.className = "listbox";
  feedList.id = "rssFeedList";
  root.appendChild(feedList);

  const logLabel = document.createElement("p");
  logLabel.className = "field-label";
  logLabel.textContent = "Journal";
  root.appendChild(logLabel);

  const logList = document.createElement("div");
  logList.className = "listbox";
  logList.id = "rssLogList";
  root.appendChild(logList);
}

function rssMatchesFilter(feed) {
  const needle = rssFilterText.trim().toLowerCase();
  return !needle || feed.url.toLowerCase().includes(needle);
}

function rssRenderFeedList() {
  const list = document.getElementById("rssFeedList");
  list.replaceChildren();

  const visible = rssFeeds.filter(rssMatchesFilter);
  if (!visible.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = "Aucun flux RSS.";
    list.appendChild(note);
    return;
  }

  visible.forEach((feed) => {
    const row = document.createElement("div");
    row.className = "row rss-feed-row";

    const urlEl = document.createElement("span");
    urlEl.className = "row-name";
    urlEl.textContent = feed.url;
    urlEl.title = feed.url;
    row.appendChild(urlEl);

    const keywordEl = document.createElement("span");
    keywordEl.textContent = feed.filterKeyword;
    keywordEl.title = feed.filterKeyword;
    row.appendChild(keywordEl);

    const enabledCheck = document.createElement("input");
    enabledCheck.type = "checkbox";
    enabledCheck.checked = feed.enabled;
    enabledCheck.addEventListener("change", () => {
      window.bridge.rss.setFeedEnabled(feed.url, enabledCheck.checked);
    });
    row.appendChild(enabledCheck);

    const actions = document.createElement("div");
    actions.className = "row-actions";
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", () => {
      window.bridge.rss.removeFeed(feed.url);
      rssFeeds = rssFeeds.filter((f) => f.url !== feed.url);
      rssRenderFeedList();
    });
    actions.appendChild(removeBtn);
    row.appendChild(actions);

    list.appendChild(row);
  });
}

function rssReloadFeeds() {
  window.bridge.rss.listFeeds((feeds) => {
    rssFeeds = feeds;
    rssRenderFeedList();
  });
}

function rssAppendLog(text, isError) {
  const list = document.getElementById("rssLogList");
  const row = document.createElement("p");
  row.className = isError ? "rss-log-row rss-log-error" : "rss-log-row";
  const timestamp = new Date().toLocaleTimeString();
  row.textContent = `[${timestamp}] ${text}`;
  list.insertBefore(row, list.firstChild);
  while (list.children.length > RSS_MAX_LOG_ENTRIES) {
    list.removeChild(list.lastChild);
  }
}

function wireRssPage() {
  rssBuildPage();
  const rssBridge = window.bridge.rss;

  document.getElementById("rssCheckNowBtn").addEventListener("click", () => {
    rssBridge.checkNow();
  });

  document.getElementById("rssAddBtn").addEventListener("click", () => {
    const url = document.getElementById("rssUrlInput").value.trim();
    const keyword = document.getElementById("rssKeywordInput").value.trim();
    rssBridge.addFeed(url, keyword, (result) => {
      document.getElementById("rssAddStatus").textContent = result.error || "";
      if (result.ok) {
        document.getElementById("rssUrlInput").value = "";
        document.getElementById("rssKeywordInput").value = "";
        rssReloadFeeds();
      }
    });
  });

  document.getElementById("rssSearchInput").addEventListener("input", (e) => {
    rssFilterText = e.target.value;
    rssRenderFeedList();
  });

  rssBridge.itemsFound.connect((feedUrl, items) => {
    items.forEach((item) => {
      const title = item.title || feedUrl;
      rssAppendLog(`${title} — ${feedUrl}`, false);
    });
  });
  rssBridge.feedCheckFailed.connect((feedUrl, message) => {
    rssAppendLog(`${feedUrl} — ${message}`, true);
  });

  rssReloadFeeds();
}
