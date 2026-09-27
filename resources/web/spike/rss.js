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
  label.textContent = t("web.rss.subscriptions_label");
  label.dataset.i18nKey = "web.rss.subscriptions_label";
  topRow.appendChild(label);
  const spacer = document.createElement("span");
  spacer.style.flex = "1";
  topRow.appendChild(spacer);
  const checkNowBtn = document.createElement("button");
  checkNowBtn.className = "start-btn";
  checkNowBtn.id = "rssCheckNowBtn";
  checkNowBtn.textContent = t("rss_tab.check_now");
  checkNowBtn.dataset.i18nKey = "rss_tab.check_now";
  topRow.appendChild(checkNowBtn);
  root.appendChild(topRow);

  const addGrid = document.createElement("div");
  addGrid.className = "form-grid";

  const urlRow = document.createElement("div");
  urlRow.className = "field-row";
  const urlLabel = document.createElement("label");
  urlLabel.className = "field-label inline";
  urlLabel.textContent = t("web.rss.feed_url_label");
  urlLabel.dataset.i18nKey = "web.rss.feed_url_label";
  const urlInput = document.createElement("input");
  urlInput.type = "text";
  urlInput.id = "rssUrlInput";
  urlInput.placeholder = t("web.rss.url_placeholder");
  urlInput.dataset.i18nPlaceholder = "web.rss.url_placeholder";
  urlRow.appendChild(urlLabel);
  urlRow.appendChild(urlInput);
  addGrid.appendChild(urlRow);

  const keywordRow = document.createElement("div");
  keywordRow.className = "field-row";
  const keywordLabel = document.createElement("label");
  keywordLabel.className = "field-label inline";
  keywordLabel.textContent = t("rss_tab.column_keyword");
  keywordLabel.dataset.i18nKey = "rss_tab.column_keyword";
  const keywordInput = document.createElement("input");
  keywordInput.type = "text";
  keywordInput.id = "rssKeywordInput";
  keywordInput.placeholder = t("web.rss.keyword_placeholder");
  keywordInput.dataset.i18nPlaceholder = "web.rss.keyword_placeholder";
  keywordRow.appendChild(keywordLabel);
  keywordRow.appendChild(keywordInput);
  addGrid.appendChild(keywordRow);

  const addBtnRow = document.createElement("div");
  addBtnRow.className = "field-row";
  const addBtn = document.createElement("button");
  addBtn.className = "start-btn";
  addBtn.id = "rssAddBtn";
  addBtn.textContent = t("common.add");
  addBtn.dataset.i18nKey = "common.add";
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
  searchInput.placeholder = t("web.search.query_placeholder");
  searchInput.dataset.i18nPlaceholder = "web.search.query_placeholder";
  root.appendChild(searchInput);

  const feedList = document.createElement("div");
  feedList.className = "listbox";
  feedList.id = "rssFeedList";
  root.appendChild(feedList);

  const logLabel = document.createElement("p");
  logLabel.className = "field-label";
  logLabel.textContent = t("web.rss.log_label");
  logLabel.dataset.i18nKey = "web.rss.log_label";
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
    note.textContent = t("web.rss.no_feeds");
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
    const filtersBtn = document.createElement("button");
    filtersBtn.textContent = t("web.rss.filters_button");
    filtersBtn.addEventListener("click", () => rssOpenFiltersDialog(feed));
    actions.appendChild(filtersBtn);
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

// Advanced filters (catalogue idea "filtres RSS avances") -- a separate
// dialog from the simple add form above, since these are optional/rare
// fields that would clutter the always-visible add row.
function rssOpenFiltersDialog(feed) {
  const content = document.createElement("div");
  content.className = "form-grid";

  function field(labelText, id, value, placeholder) {
    const row = document.createElement("div");
    row.className = "field-row";
    const label = document.createElement("label");
    label.className = "field-label inline";
    label.textContent = labelText;
    label.htmlFor = id;
    const input = document.createElement("input");
    input.type = "text";
    input.id = id;
    input.value = value || "";
    if (placeholder) input.placeholder = placeholder;
    row.appendChild(label);
    row.appendChild(input);
    content.appendChild(row);
    return input;
  }

  const includeInput = field(t("web.rss.filter_include_label"), "rssFilterInclude", feed.regexInclude, t("web.rss.filter_include_placeholder"));
  const excludeInput = field(t("web.rss.filter_exclude_label"), "rssFilterExclude", feed.regexExclude, t("web.rss.filter_exclude_placeholder"));
  const minInput = field(t("web.rss.filter_res_min_label"), "rssFilterResMin", feed.resolutionMin || "", t("web.rss.filter_res_min_placeholder"));
  const maxInput = field(t("web.rss.filter_res_max_label"), "rssFilterResMax", feed.resolutionMax || "", t("web.rss.filter_res_max_placeholder"));

  const latestRow = document.createElement("div");
  latestRow.className = "field-row";
  const latestCheck = document.createElement("input");
  latestCheck.type = "checkbox";
  latestCheck.id = "rssFilterLatestOnly";
  latestCheck.checked = !!feed.latestEpisodeOnly;
  const latestLabel = document.createElement("label");
  latestLabel.className = "field-label inline";
  latestLabel.textContent = t("web.rss.filter_latest_only_label");
  latestLabel.htmlFor = "rssFilterLatestOnly";
  latestRow.appendChild(latestCheck);
  latestRow.appendChild(latestLabel);
  content.appendChild(latestRow);

  const buttonRow = document.createElement("div");
  buttonRow.className = "modal-close-row";
  const saveBtn = document.createElement("button");
  saveBtn.textContent = t("web.rss.filters_save_button");
  saveBtn.addEventListener("click", () => {
    window.bridge.rss.updateFeedFilters(feed.url, {
      regexInclude: includeInput.value.trim(),
      regexExclude: excludeInput.value.trim(),
      resolutionMin: parseInt(minInput.value, 10) || 0,
      resolutionMax: parseInt(maxInput.value, 10) || 0,
      latestEpisodeOnly: latestCheck.checked,
    });
    closeModal();
    rssReloadFeeds();
  });
  buttonRow.appendChild(saveBtn);
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = t("common.cancel");
  cancelBtn.addEventListener("click", () => closeModal());
  buttonRow.appendChild(cancelBtn);
  content.appendChild(buttonRow);

  openModal(t("web.rss.filters_dialog_title", { url: feed.url }), content);
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
      rssAppendLog(t("web.rss.log_entry", { title, url: feedUrl }), false);
    });
  });
  rssBridge.feedCheckFailed.connect((feedUrl, message) => {
    rssAppendLog(t("web.rss.log_feed_check_failed", { url: feedUrl, message }), true);
  });

  rssReloadFeeds();
}
