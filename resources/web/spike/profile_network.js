// Profile tab -- "Network" group: NetworkPrivacySection (save-on-click) +
// SecurityCenterSection (read-only) + RemoteAccessSection (enabled checkbox
// and "regenerate token" are live-apply, matching native).

const PROXY_TYPE_LABELS = {
  none: "Aucun",
  socks5: "SOCKS5",
  socks5_pw: "SOCKS5 (avec identifiants)",
  http: "HTTP",
  http_pw: "HTTP (avec identifiants)",
};
const ENCRYPTION_MODE_LABELS = { forced: "Forcé", enabled: "Activé", disabled: "Désactivé" };

function pnSectionHeading(text) {
  const h = document.createElement("h3");
  h.className = "profile-section-heading";
  h.textContent = text;
  return h;
}

function pnLabeledField(labelText, field, forId, tooltipText) {
  const label = document.createElement("label");
  label.className = "field-label";
  label.textContent = labelText;
  if (forId) label.htmlFor = forId;
  if (tooltipText) label.appendChild(makeInfoHint(tooltipText));
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
  label.textContent = labelText;
  label.htmlFor = id;
  if (tooltipText) label.appendChild(makeInfoHint(tooltipText));
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
    opt.textContent = text;
    select.appendChild(opt);
  });
  return select;
}

function pnStatusRow(labelText) {
  const row = document.createElement("div");
  row.className = "field-row";
  const label = document.createElement("span");
  label.className = "field-label inline";
  label.textContent = labelText;
  const value = document.createElement("span");
  value.className = "field-note pn-status-value";
  row.appendChild(label);
  row.appendChild(value);
  return { row, value };
}

function buildNetworkPrivacySection(container, bridge) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(pnSectionHeading("Réseau et proxy"));

  const form = document.createElement("div");
  form.className = "form-grid";
  section.appendChild(form);

  const restrictRow = pnCheckboxRow(
    "Restreindre la découverte (DHT/LSD) aux pairs du tracker",
    "pnRestrictDiscovery",
    "DHT et LSD permettent de trouver des pairs même sans tracker actif (recherche décentralisée sur Internet et sur le réseau local). Cocher cette option limite la découverte aux seuls pairs annoncés par le tracker, au prix de pairs potentiellement moins nombreux."
  );
  form.appendChild(restrictRow.row);

  const proxyEnabledRow = pnCheckboxRow("Activer le proxy", "pnProxyEnabled");
  form.appendChild(proxyEnabledRow.row);

  const proxyTypeSelect = pnSelect("pnProxyType", PROXY_TYPE_LABELS);
  form.appendChild(pnLabeledField("Type de proxy", proxyTypeSelect, "pnProxyType"));

  const proxyHostInput = document.createElement("input");
  proxyHostInput.type = "text";
  proxyHostInput.id = "pnProxyHost";
  proxyHostInput.placeholder = "proxy.example.com";
  form.appendChild(pnLabeledField("Hôte du proxy", proxyHostInput, "pnProxyHost"));

  const proxyPortInput = document.createElement("input");
  proxyPortInput.type = "number";
  proxyPortInput.id = "pnProxyPort";
  proxyPortInput.min = "0";
  proxyPortInput.max = "65535";
  form.appendChild(pnLabeledField("Port du proxy", proxyPortInput, "pnProxyPort"));

  const proxyUsernameInput = document.createElement("input");
  proxyUsernameInput.type = "text";
  proxyUsernameInput.id = "pnProxyUsername";
  form.appendChild(pnLabeledField("Identifiant du proxy", proxyUsernameInput, "pnProxyUsername"));

  const proxyPasswordInput = document.createElement("input");
  proxyPasswordInput.type = "password";
  proxyPasswordInput.id = "pnProxyPassword";
  form.appendChild(pnLabeledField("Mot de passe du proxy", proxyPasswordInput, "pnProxyPassword"));

  const forceProxyRow = pnCheckboxRow(
    "Bloquer toute connexion directe si le proxy est indisponible (kill switch)",
    "pnForceProxy"
  );
  form.appendChild(forceProxyRow.row);

  const interfaceInput = document.createElement("input");
  interfaceInput.type = "text";
  interfaceInput.id = "pnNetworkInterface";
  interfaceInput.placeholder = "Par défaut (toutes les interfaces)";
  form.appendChild(pnLabeledField("Interface réseau", interfaceInput, "pnNetworkInterface"));

  const encryptionSelect = pnSelect("pnEncryptionMode", ENCRYPTION_MODE_LABELS);
  form.appendChild(pnLabeledField(
    "Chiffrement du protocole",
    encryptionSelect,
    "pnEncryptionMode",
    "Chiffre le trafic BitTorrent pour le rendre plus difficile à repérer par un pare-feu ou un FAI qui bride ce type de trafic. « Forcé » refuse toute connexion non chiffrée ; « Désactivé » n'en propose aucune."
  ));

  const saveBtn = document.createElement("button");
  saveBtn.className = "start-btn";
  saveBtn.textContent = "Enregistrer";
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
    };
    bridge.saveSettings(values, (result) => {
      status.textContent = result.ok ? "Paramètres enregistrés." : result.error || "";
    });
  });

  container.appendChild(section);
}

function buildSecurityCenterSection(container, bridge) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(pnSectionHeading("Centre de sécurité"));

  const form = document.createElement("div");
  form.className = "form-grid";
  section.appendChild(form);

  const proxyStatus = pnStatusRow("Proxy");
  form.appendChild(proxyStatus.row);
  const discoveryStatus = pnStatusRow("Découverte restreinte");
  form.appendChild(discoveryStatus.row);
  const encryptionStatus = pnStatusRow("Chiffrement");
  form.appendChild(encryptionStatus.row);
  const riskStatus = pnStatusRow("Analyses de risque");
  form.appendChild(riskStatus.row);

  const refreshBtn = document.createElement("button");
  refreshBtn.textContent = "Actualiser";
  section.appendChild(refreshBtn);

  function refresh() {
    bridge.getSecuritySnapshot((snap) => {
      proxyStatus.value.textContent = snap.proxyEnabled ? "Actif" : "Inactif";
      discoveryStatus.value.textContent = snap.discoveryRestricted ? "Actif" : "Inactif";
      encryptionStatus.value.textContent = ENCRYPTION_MODE_LABELS[snap.encryptionMode] || snap.encryptionMode;
      riskStatus.value.textContent =
        snap.scannedCount === 0
          ? "Aucune analyse pour l'instant"
          : `${snap.scannedCount} analysé(s), ${snap.flaggedCount} signalé(s)`;
    });
  }

  refreshBtn.addEventListener("click", refresh);
  refresh();

  container.appendChild(section);
}

function buildRemoteAccessSection(container, bridge) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(pnSectionHeading("Accès distant"));

  const enabledRow = pnCheckboxRow("Activer l'accès distant (réseau local)", "pnRemoteEnabled");
  section.appendChild(enabledRow.row);

  const form = document.createElement("div");
  form.className = "form-grid";
  section.appendChild(form);

  const urlValue = document.createElement("span");
  urlValue.className = "field-note pn-status-value";
  form.appendChild(pnLabeledField("URL", urlValue));

  const portInput = document.createElement("input");
  portInput.type = "number";
  portInput.id = "pnRemotePort";
  portInput.min = "1";
  portInput.max = "65535";
  form.appendChild(pnLabeledField("Port", portInput, "pnRemotePort"));

  const tokenValue = document.createElement("span");
  tokenValue.className = "field-note pn-status-value";
  form.appendChild(pnLabeledField("Jeton", tokenValue));

  const regenerateBtn = document.createElement("button");
  regenerateBtn.textContent = "Régénérer le jeton";
  section.appendChild(regenerateBtn);

  const status = document.createElement("p");
  status.className = "status-line";
  section.appendChild(status);

  function refresh() {
    bridge.getRemoteAccessInfo((info) => {
      enabledRow.input.checked = !!info.enabled;
      portInput.value = info.port;
      urlValue.textContent = info.token ? `${info.url}/?token=${info.token}` : "Non démarré";
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
