// Profile tab -- "Network" group: NetworkPrivacySection (save-on-click) +
// SecurityCenterSection (read-only) + RemoteAccessSection (enabled checkbox
// and "regenerate token" are live-apply, matching native).

const PROXY_TYPE_LABELS = {
  none: "proxy_type.none",
  socks5: "proxy_type.socks5",
  socks5_pw: "web.profile_network.proxy_type_socks5_pw",
  http: "proxy_type.http",
  http_pw: "web.profile_network.proxy_type_http_pw",
};
const ENCRYPTION_MODE_LABELS = {
  forced: "web.profile_network.encryption_mode_forced",
  enabled: "web.profile_network.encryption_mode_enabled",
  disabled: "encryption_mode.disabled",
};

function pnSectionHeading(text) {
  const h = document.createElement("h3");
  h.className = "profile-section-heading";
  h.textContent = t(text);
  h.dataset.i18nKey = text;
  return h;
}

function pnLabeledField(labelText, field, forId, tooltipText) {
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = t(labelText);
  label.dataset.i18nKey = labelText;
  if (forId) label.htmlFor = forId;
  if (tooltipText) label.appendChild(makeInfoHint(t(tooltipText)));
  const wrap = document.createElement("div");
  wrap.className = "form-grid";
  wrap.appendChild(label);
  wrap.appendChild(field);
  return wrap;
}

function pnCheckboxRow(labelText, id, tooltipText) {
  const row = document.createElement("div");
  row.className = "field-row";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.id = id;
  const label = document.createElement("label");
  label.className = "field-label inline";
  label.textContent = t(labelText);
  label.dataset.i18nKey = labelText;
  label.htmlFor = id;
  if (tooltipText) label.appendChild(makeInfoHint(t(tooltipText)));
  row.appendChild(input);
  row.appendChild(label);
  return { row, input };
}

function pnSelect(id, optionsMap) {
  const select = document.createElement("select");
  select.id = id;
  Object.entries(optionsMap).forEach(([value, text]) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = t(text);
    opt.dataset.i18nKey = text;
    select.appendChild(opt);
  });
  return select;
}

function pnStatusRow(labelText) {
  const row = document.createElement("div");
  row.className = "field-row";
  const label = document.createElement("span");
  label.className = "field-label inline";
  label.textContent = t(labelText);
  label.dataset.i18nKey = labelText;
  const value = document.createElement("span");
  value.className = "field-note pn-status-value";
  row.appendChild(label);
  row.appendChild(value);
  return { row, value };
}

function buildNetworkPrivacySection(container, bridge) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(pnSectionHeading("web.profile_network.heading"));

  const form = document.createElement("div");
  form.className = "form-grid";
  section.appendChild(form);

  const restrictRow = pnCheckboxRow(
    "web.profile_network.restrict_discovery_checkbox",
    "pnRestrictDiscovery",
    "web.profile_network.restrict_discovery_tooltip"
  );
  form.appendChild(restrictRow.row);

  const proxyEnabledRow = pnCheckboxRow("profile_tab.proxy_enabled", "pnProxyEnabled");
  form.appendChild(proxyEnabledRow.row);

  const proxyTypeSelect = pnSelect("pnProxyType", PROXY_TYPE_LABELS);
  form.appendChild(pnLabeledField("web.profile_network.proxy_type_label", proxyTypeSelect, "pnProxyType"));

  const proxyHostInput = document.createElement("input");
  proxyHostInput.type = "text";
  proxyHostInput.id = "pnProxyHost";
  proxyHostInput.placeholder = t("web.profile_network.proxy_host_placeholder");
  proxyHostInput.dataset.i18nPlaceholder = "web.profile_network.proxy_host_placeholder";
  form.appendChild(pnLabeledField("web.profile_network.proxy_host_label", proxyHostInput, "pnProxyHost"));

  const proxyPortInput = document.createElement("input");
  proxyPortInput.type = "number";
  proxyPortInput.id = "pnProxyPort";
  proxyPortInput.min = "0";
  proxyPortInput.max = "65535";
  form.appendChild(pnLabeledField("web.profile_network.proxy_port_label", proxyPortInput, "pnProxyPort"));

  const proxyUsernameInput = document.createElement("input");
  proxyUsernameInput.type = "text";
  proxyUsernameInput.id = "pnProxyUsername";
  form.appendChild(pnLabeledField("web.profile_network.proxy_username_label", proxyUsernameInput, "pnProxyUsername"));

  const proxyPasswordInput = document.createElement("input");
  proxyPasswordInput.type = "password";
  proxyPasswordInput.id = "pnProxyPassword";
  form.appendChild(pnLabeledField("web.profile_network.proxy_password_label", proxyPasswordInput, "pnProxyPassword"));

  const forceProxyRow = pnCheckboxRow(
    "web.profile_network.force_proxy_checkbox",
    "pnForceProxy"
  );
  form.appendChild(forceProxyRow.row);

  const interfaceInput = document.createElement("input");
  interfaceInput.type = "text";
  interfaceInput.id = "pnNetworkInterface";
  interfaceInput.placeholder = t("web.profile_network.network_interface_placeholder");
  interfaceInput.dataset.i18nPlaceholder = "web.profile_network.network_interface_placeholder";
  form.appendChild(pnLabeledField("web.profile_network.network_interface_label", interfaceInput, "pnNetworkInterface"));

  const encryptionSelect = pnSelect("pnEncryptionMode", ENCRYPTION_MODE_LABELS);
  form.appendChild(pnLabeledField(
    "web.profile_network.encryption_mode_label",
    encryptionSelect,
    "pnEncryptionMode",
    "web.profile_network.encryption_mode_tooltip"
  ));

  const blocklistEnabledRow = pnCheckboxRow(
    "web.profile_network.ip_blocklist_enabled_checkbox",
    "pnIpBlocklistEnabled",
    "web.profile_network.ip_blocklist_enabled_tooltip"
  );
  form.appendChild(blocklistEnabledRow.row);

  const blocklistPathRow = document.createElement("div");
  blocklistPathRow.className = "field-row";
  const blocklistPathInput = document.createElement("input");
  blocklistPathInput.type = "text";
  blocklistPathInput.id = "pnIpBlocklistPath";
  blocklistPathInput.placeholder = t("web.profile_network.ip_blocklist_path_placeholder");
  blocklistPathInput.dataset.i18nPlaceholder = "web.profile_network.ip_blocklist_path_placeholder";
  blocklistPathRow.appendChild(blocklistPathInput);
  const blocklistBrowseBtn = document.createElement("button");
  blocklistBrowseBtn.textContent = t("web.profile_network.browse_button");
  blocklistBrowseBtn.dataset.i18nKey = "web.profile_network.browse_button";
  blocklistBrowseBtn.addEventListener("click", () => {
    window.bridge.dialogs.browseOpenFile("Listes noires (*.txt *.dat);;Tous les fichiers (*)", (path) => {
      if (path) blocklistPathInput.value = path;
    });
  });
  blocklistPathRow.appendChild(blocklistBrowseBtn);
  form.appendChild(pnLabeledField("web.profile_network.ip_blocklist_path_label", blocklistPathRow, "pnIpBlocklistPath"));

  const saveBtn = document.createElement("button");
  saveBtn.className = "start-btn";
  saveBtn.textContent = t("profile_tab.save_button");
  saveBtn.dataset.i18nKey = "profile_tab.save_button";
  section.appendChild(saveBtn);

  const status = document.createElement("p");
  status.className = "status-line";
  section.appendChild(status);

  function populate(values) {
    restrictRow.input.checked = !!values.restrictDiscovery;
    proxyEnabledRow.input.checked = !!values.proxyEnabled;
    proxyTypeSelect.value = values.proxyType;
    proxyHostInput.value = values.proxyHost;
    proxyPortInput.value = values.proxyPort;
    proxyUsernameInput.value = values.proxyUsername;
    proxyPasswordInput.value = values.proxyPassword;
    forceProxyRow.input.checked = !!values.forceProxy;
    interfaceInput.value = values.networkInterface;
    encryptionSelect.value = values.encryptionMode;
    blocklistEnabledRow.input.checked = !!values.ipBlocklistEnabled;
    blocklistPathInput.value = values.ipBlocklistPath;
  }

  bridge.getSettings(populate);

  saveBtn.addEventListener("click", () => {
    const values = {
      restrictDiscovery: restrictRow.input.checked,
      proxyEnabled: proxyEnabledRow.input.checked,
      proxyType: proxyTypeSelect.value,
      proxyHost: proxyHostInput.value,
      proxyPort: parseInt(proxyPortInput.value, 10) || 0,
      proxyUsername: proxyUsernameInput.value,
      proxyPassword: proxyPasswordInput.value,
      forceProxy: forceProxyRow.input.checked,
      networkInterface: interfaceInput.value,
      encryptionMode: encryptionSelect.value,
      ipBlocklistEnabled: blocklistEnabledRow.input.checked,
      ipBlocklistPath: blocklistPathInput.value,
    };
    bridge.saveSettings(values, (result) => {
      status.textContent = result.ok ? t("web.profile_network.settings_saved") : result.error || "";
    });
  });

  container.appendChild(section);
}

function buildSecurityCenterSection(container, bridge) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(pnSectionHeading("security_center.group"));

  const form = document.createElement("div");
  form.className = "form-grid";
  section.appendChild(form);

  const proxyStatus = pnStatusRow("web.profile_network.security_proxy_label");
  form.appendChild(proxyStatus.row);
  const discoveryStatus = pnStatusRow("web.profile_network.security_discovery_label");
  form.appendChild(discoveryStatus.row);
  const encryptionStatus = pnStatusRow("web.profile_network.security_encryption_label");
  form.appendChild(encryptionStatus.row);
  const riskStatus = pnStatusRow("web.profile_network.security_risk_label");
  form.appendChild(riskStatus.row);

  const refreshBtn = document.createElement("button");
  refreshBtn.textContent = t("security_center.refresh_button");
  refreshBtn.dataset.i18nKey = "security_center.refresh_button";
  section.appendChild(refreshBtn);

  function refresh() {
    bridge.getSecuritySnapshot((snap) => {
      proxyStatus.value.textContent = snap.proxyEnabled ? t("security_center.status_active") : t("security_center.status_inactive");
      discoveryStatus.value.textContent = snap.discoveryRestricted ? t("security_center.status_active") : t("security_center.status_inactive");
      encryptionStatus.value.textContent = ENCRYPTION_MODE_LABELS[snap.encryptionMode]
        ? t(ENCRYPTION_MODE_LABELS[snap.encryptionMode])
        : snap.encryptionMode;
      riskStatus.value.textContent =
        snap.scannedCount === 0
          ? t("web.profile_network.risk_no_scans")
          : t("web.profile_network.risk_summary", { scanned: snap.scannedCount, flagged: snap.flaggedCount });
    });
  }

  refreshBtn.addEventListener("click", refresh);
  refresh();

  container.appendChild(section);
}

function buildRemoteAccessSection(container, bridge) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(pnSectionHeading("remote_access.group"));

  const enabledRow = pnCheckboxRow("remote_access.enabled_checkbox", "pnRemoteEnabled");
  section.appendChild(enabledRow.row);

  const form = document.createElement("div");
  form.className = "form-grid";
  section.appendChild(form);

  const urlValue = document.createElement("span");
  urlValue.className = "field-note pn-status-value";
  form.appendChild(pnLabeledField("web.profile_network.remote_url_label", urlValue));

  const portInput = document.createElement("input");
  portInput.type = "number";
  portInput.id = "pnRemotePort";
  portInput.min = "1";
  portInput.max = "65535";
  form.appendChild(pnLabeledField("web.profile_network.remote_port_label", portInput, "pnRemotePort"));

  const tokenValue = document.createElement("span");
  tokenValue.className = "field-note pn-status-value";
  form.appendChild(pnLabeledField("web.profile_network.remote_token_label", tokenValue));

  const regenerateBtn = document.createElement("button");
  regenerateBtn.textContent = t("remote_access.regenerate_button");
  regenerateBtn.dataset.i18nKey = "remote_access.regenerate_button";
  section.appendChild(regenerateBtn);

  const status = document.createElement("p");
  status.className = "status-line";
  section.appendChild(status);

  function refresh() {
    bridge.getRemoteAccessInfo((info) => {
      enabledRow.input.checked = !!info.enabled;
      portInput.value = info.port;
      urlValue.textContent = info.token ? `${info.url}/?token=${info.token}` : t("web.profile_network.remote_not_started");
      tokenValue.textContent = info.token || "";
    });
  }

  enabledRow.input.addEventListener("change", () => {
    bridge.setRemoteAccessEnabled(enabledRow.input.checked, (result) => {
      if (!result.ok) {
        enabledRow.input.checked = false;
        status.textContent = result.error || "";
      } else {
        status.textContent = "";
      }
      refresh();
    });
  });

  portInput.addEventListener("change", () => {
    bridge.setRemoteAccessPort(parseInt(portInput.value, 10) || 0);
  });

  regenerateBtn.addEventListener("click", () => {
    bridge.regenerateToken(() => refresh());
  });

  refresh();

  container.appendChild(section);
}

function wireProfileNetwork() {
  const bridge = window.bridge.profileNetwork;
  const container = document.getElementById("profileNetworkContainer");
  buildNetworkPrivacySection(container, bridge);
  buildSecurityCenterSection(container, bridge);
  buildRemoteAccessSection(container, bridge);
}
