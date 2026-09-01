// Profile tab -- "Advanced/Rules" group: RoutingRulesSection +
// SettingsProfilesSection (see routing_rules_section.py/
// settings_profiles_section.py). Both are fully live-apply -- every action
// hits the bridge/store directly, there's no batched "Enregistrer" button
// for this group.

const AR_FIELD_LABELS = { name: "Nom du torrent", tracker: "Tracker" };

function arSectionHeading(text) {
  const h = document.createElement("h3");
  h.className = "profile-section-heading";
  h.textContent = text;
  return h;
}

// ---------------------------------------------------------------- routing rules

let arRules = [];
let arEditingName = null; // non-null while the inline form is editing an existing rule

function arRuleRow(rule, index) {
  const row = document.createElement("div");
  row.className = "rule-row";

  const nameEl = document.createElement("span");
  nameEl.className = "rule-cell";
  nameEl.textContent = rule.name;
  nameEl.title = rule.name;
  row.appendChild(nameEl);

  const patternEl = document.createElement("span");
  patternEl.className = "rule-cell";
  patternEl.textContent = rule.pattern;
  patternEl.title = rule.pattern;
  row.appendChild(patternEl);

  const fieldEl = document.createElement("span");
  fieldEl.className = "rule-cell";
  fieldEl.textContent = AR_FIELD_LABELS[rule.matchField] || rule.matchField;
  row.appendChild(fieldEl);

  const destEl = document.createElement("span");
  destEl.className = "rule-cell";
  destEl.textContent = rule.destination;
  destEl.title = rule.destination;
  row.appendChild(destEl);

  const actions = document.createElement("div");
  actions.className = "row-actions";

  const upBtn = document.createElement("button");
  upBtn.textContent = "▲";
  upBtn.disabled = index === 0;
  upBtn.addEventListener("click", () => arMoveRule(index, index - 1));
  actions.appendChild(upBtn);

  const downBtn = document.createElement("button");
  downBtn.textContent = "▼";
  downBtn.disabled = index === arRules.length - 1;
  downBtn.addEventListener("click", () => arMoveRule(index, index + 1));
  actions.appendChild(downBtn);

  const editBtn = document.createElement("button");
  editBtn.textContent = "Modifier";
  editBtn.addEventListener("click", () => arOpenForm(rule));
  actions.appendChild(editBtn);

  const removeBtn = document.createElement("button");
  removeBtn.textContent = "Retirer";
  removeBtn.addEventListener("click", () => arDeleteRule(rule.name));
  actions.appendChild(removeBtn);

  row.appendChild(actions);
  return row;
}

function arRenderRules() {
  const list = document.getElementById("arRulesList");
  list.replaceChildren();
  if (!arRules.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = "Aucune règle de classement pour l'instant.";
    list.appendChild(note);
    return;
  }
  arRules.forEach((rule, index) => list.appendChild(arRuleRow(rule, index)));
}

function arReloadRules() {
  window.bridge.profileAdvanced.listRoutingRules((rules) => {
    arRules = rules;
    arRenderRules();
  });
}

function arMoveRule(from, to) {
  // Mutation is fire-and-forget (no result= on this slot, so nothing to
  // reject it) and the new order is already known locally -- updating
  // arRules directly and re-rendering avoids a round-trip re-fetch of the
  // same list this call just reordered.
  [arRules[from], arRules[to]] = [arRules[to], arRules[from]];
  window.bridge.profileAdvanced.reorderRoutingRules(arRules.map((r) => r.name));
  arRenderRules();
}

function arDeleteRule(name) {
  if (!confirm(`Voulez-vous vraiment supprimer la règle « ${name} » ?`)) return;
  window.bridge.profileAdvanced.deleteRoutingRule(name);
  arRules = arRules.filter((r) => r.name !== name);
  arRenderRules();
}

function arOpenForm(rule) {
  arEditingName = rule ? rule.name : null;
  document.getElementById("arFormTitle").textContent = rule ? "Modifier la règle" : "Ajouter une règle";
  document.getElementById("arNameInput").value = rule ? rule.name : "";
  document.getElementById("arPatternInput").value = rule ? rule.pattern : "";
  document.getElementById("arFieldSelect").value = rule ? rule.matchField : "name";
  document.getElementById("arDestInput").value = rule ? rule.destination : "";
  document.getElementById("arFormStatus").textContent = "";
  document.getElementById("arForm").style.display = "";
}

function arCloseForm() {
  document.getElementById("arForm").style.display = "none";
  arEditingName = null;
}

function arBuildRulesSection(container) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(arSectionHeading("Règles de routage"));

  const intro = document.createElement("p");
  intro.className = "field-note";
  intro.textContent =
    "Définissez des règles « si le nom ou le tracker contient X, alors dossier Y » pour orienter " +
    "automatiquement chaque nouveau torrent. La première règle qui correspond l'emporte -- utilisez " +
    "▲/▼ pour les prioriser.";
  section.appendChild(intro);

  const header = document.createElement("div");
  header.className = "rule-row rule-header";
  ["Nom", "Motif", "Champ", "Destination", ""].forEach((label) => {
    const cell = document.createElement("span");
    cell.textContent = label;
    header.appendChild(cell);
  });
  section.appendChild(header);

  const list = document.createElement("div");
  list.id = "arRulesList";
  list.className = "listbox";
  section.appendChild(list);

  const addBtnRow = document.createElement("div");
  addBtnRow.className = "field-row";
  const addBtn = document.createElement("button");
  addBtn.textContent = "Ajouter";
  addBtn.addEventListener("click", () => arOpenForm(null));
  addBtnRow.appendChild(addBtn);
  section.appendChild(addBtnRow);

  // Inline add/edit form -- no native modal equivalent, just show/hide.
  const form = document.createElement("div");
  form.id = "arForm";
  form.className = "form-grid";
  form.style.display = "none";

  const formTitle = document.createElement("p");
  formTitle.id = "arFormTitle";
  formTitle.className = "field-label";
  form.appendChild(formTitle);

  const nameRow = document.createElement("div");
  nameRow.className = "field-row";
  const nameLabel = document.createElement("label");
  nameLabel.className = "field-label inline";
  nameLabel.textContent = "Nom de la règle :";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.id = "arNameInput";
  nameRow.appendChild(nameLabel);
  nameRow.appendChild(nameInput);
  form.appendChild(nameRow);

  const patternRow = document.createElement("div");
  patternRow.className = "field-row";
  const patternLabel = document.createElement("label");
  patternLabel.className = "field-label inline";
  patternLabel.textContent = "Motif (sous-chaîne) :";
  const patternInput = document.createElement("input");
  patternInput.type = "text";
  patternInput.id = "arPatternInput";
  patternRow.appendChild(patternLabel);
  patternRow.appendChild(patternInput);
  form.appendChild(patternRow);

  const fieldRow = document.createElement("div");
  fieldRow.className = "field-row";
  const fieldLabel = document.createElement("label");
  fieldLabel.className = "field-label inline";
  fieldLabel.textContent = "Champ à vérifier :";
  const fieldSelect = document.createElement("select");
  fieldSelect.id = "arFieldSelect";
  Object.entries(AR_FIELD_LABELS).forEach(([value, text]) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = text;
    fieldSelect.appendChild(opt);
  });
  fieldRow.appendChild(fieldLabel);
  fieldRow.appendChild(fieldSelect);
  form.appendChild(fieldRow);

  const destRow = document.createElement("div");
  destRow.className = "field-row";
  const destLabel = document.createElement("label");
  destLabel.className = "field-label inline";
  destLabel.textContent = "Dossier de destination :";
  const destInput = document.createElement("input");
  destInput.type = "text";
  destInput.id = "arDestInput";
  const destBrowseBtn = document.createElement("button");
  destBrowseBtn.textContent = "Parcourir...";
  destBrowseBtn.addEventListener("click", () => {
    window.bridge.dialogs.browseFolder(destInput.value, (path) => {
      if (path) destInput.value = path;
    });
  });
  destRow.appendChild(destLabel);
  destRow.appendChild(destInput);
  destRow.appendChild(destBrowseBtn);
  form.appendChild(destRow);

  const formStatus = document.createElement("p");
  formStatus.id = "arFormStatus";
  formStatus.className = "status-line";
  form.appendChild(formStatus);

  const formBtnRow = document.createElement("div");
  formBtnRow.className = "field-row";
  const saveBtn = document.createElement("button");
  saveBtn.className = "start-btn";
  saveBtn.textContent = "Enregistrer";
  saveBtn.addEventListener("click", () => {
    const name = nameInput.value.trim();
    const pattern = patternInput.value.trim();
    const destination = destInput.value.trim();
    if (!name || !pattern || !destination) {
      formStatus.textContent = "Le nom, le motif et le dossier de destination sont obligatoires.";
      return;
    }
    if (arEditingName && arEditingName !== name) {
      // Renamed: drop the old entry first so it isn't left behind
      // alongside the new one under a different name.
      window.bridge.profileAdvanced.deleteRoutingRule(arEditingName);
    }
    window.bridge.profileAdvanced.saveRoutingRule(name, pattern, fieldSelect.value, destination);
    arCloseForm();
    arReloadRules();
  });
  formBtnRow.appendChild(saveBtn);
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = "Annuler";
  cancelBtn.addEventListener("click", arCloseForm);
  formBtnRow.appendChild(cancelBtn);
  form.appendChild(formBtnRow);

  section.appendChild(form);
  container.appendChild(section);
}

// ------------------------------------------------------------ settings profiles

let arProfiles = [];

function arRefreshProfileCombo(selectName) {
  const combo = document.getElementById("apProfileSelect");
  combo.replaceChildren();
  // The network-profile-switch section (below) picks a profile from the
  // same list -- kept in sync here rather than duplicating the reload call,
  // guarded since this runs before that section exists on the very first
  // page build. A single pass builds each <option> once and clones it into
  // the second select instead of iterating arProfiles twice.
  const anpSelect = document.getElementById("anpProfileSelect");
  if (anpSelect) anpSelect.replaceChildren();
  arProfiles.forEach((profile) => {
    const opt = document.createElement("option");
    opt.value = profile.name;
    opt.textContent = profile.name;
    combo.appendChild(opt);
    if (anpSelect) anpSelect.appendChild(opt.cloneNode(true));
  });
  if (selectName) combo.value = selectName;
  const hasProfiles = arProfiles.length > 0;
  document.getElementById("apApplyBtn").disabled = !hasProfiles;
  document.getElementById("apDeleteBtn").disabled = !hasProfiles;
}

function arReloadProfiles(selectName) {
  window.bridge.profileAdvanced.listSettingsProfiles((profiles) => {
    arProfiles = profiles;
    arRefreshProfileCombo(selectName);
  });
}

function arBuildProfilesSection(container) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(arSectionHeading("Profils de réglages"));

  const intro = document.createElement("p");
  intro.className = "field-note";
  intro.textContent =
    "Enregistrez le proxy, le chiffrement, les notifications, les limites de débit et la restriction " +
    "DHT/PEX/LSD actuels sous un profil nommé (ex. « voyage », « connexion mobile »), pour tout " +
    "réappliquer en un clic la prochaine fois.";
  section.appendChild(intro);

  const comboRow = document.createElement("div");
  comboRow.className = "field-row";
  const comboLabel = document.createElement("label");
  comboLabel.className = "field-label inline";
  comboLabel.textContent = "Profil";
  const combo = document.createElement("select");
  combo.id = "apProfileSelect";
  comboRow.appendChild(comboLabel);
  comboRow.appendChild(combo);
  section.appendChild(comboRow);

  const btnRow = document.createElement("div");
  btnRow.className = "field-row";
  const applyBtn = document.createElement("button");
  applyBtn.id = "apApplyBtn";
  applyBtn.className = "start-btn";
  applyBtn.textContent = "Appliquer";
  btnRow.appendChild(applyBtn);
  const saveAsBtn = document.createElement("button");
  saveAsBtn.id = "apSaveAsBtn";
  saveAsBtn.textContent = "Enregistrer le profil actuel sous...";
  btnRow.appendChild(saveAsBtn);
  const deleteBtn = document.createElement("button");
  deleteBtn.id = "apDeleteBtn";
  deleteBtn.textContent = "Supprimer";
  btnRow.appendChild(deleteBtn);
  section.appendChild(btnRow);

  const status = document.createElement("p");
  status.id = "apStatus";
  status.className = "status-line";
  section.appendChild(status);

  applyBtn.addEventListener("click", () => {
    const name = combo.value;
    if (!name) return;
    window.bridge.profileAdvanced.applyProfile(name, (result) => {
      status.textContent = result.ok ? "Profil appliqué." : result.error || "Erreur lors de l'application.";
    });
  });

  saveAsBtn.addEventListener("click", () => {
    const name = (prompt("Nom du profil :") || "").trim();
    if (!name) return;
    window.bridge.profileAdvanced.saveCurrentAsProfile(name, () => {
      status.textContent = "Profil enregistré.";
      arReloadProfiles(name);
    });
  });

  deleteBtn.addEventListener("click", () => {
    const name = combo.value;
    if (!name) return;
    if (!confirm(`Voulez-vous vraiment supprimer le profil « ${name} » ?`)) return;
    window.bridge.profileAdvanced.deleteSettingsProfile(name);
    status.textContent = "";
    arReloadProfiles();
  });

  container.appendChild(section);
}

// ------------------------------------------------- network profile auto-switch

function anpRenderAssociations(list) {
  const box = document.getElementById("anpList");
  box.replaceChildren();
  if (!list.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = "Aucune association réseau -> profil pour l'instant.";
    box.appendChild(note);
    return;
  }
  list.forEach((assoc) => {
    const row = document.createElement("div");
    row.className = "row";

    const ssidEl = document.createElement("span");
    ssidEl.className = "row-name";
    ssidEl.textContent = assoc.ssid;
    ssidEl.title = assoc.ssid;
    row.appendChild(ssidEl);

    const profileEl = document.createElement("span");
    profileEl.textContent = assoc.profileName;
    profileEl.title = assoc.profileName;
    row.appendChild(profileEl);

    const actions = document.createElement("div");
    actions.className = "row-actions";
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", () => {
      window.bridge.profileAdvanced.deleteNetworkProfileAssociation(assoc.ssid);
      // Fire-and-forget mutation with a known result -- filter the list
      // this render already has (in closure) and re-render, instead of a
      // round-trip re-fetch of what was just removed locally.
      anpRenderAssociations(list.filter((a) => a.ssid !== assoc.ssid));
    });
    actions.appendChild(removeBtn);
    row.appendChild(actions);

    box.appendChild(row);
  });
}

function anpReloadAssociations() {
  window.bridge.profileAdvanced.listNetworkProfileAssociations((list) => {
    anpRenderAssociations(list);
  });
}

function anpBuildSection(container) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(arSectionHeading("Bascule automatique de profil selon le réseau Wi-Fi"));

  const intro = document.createElement("p");
  intro.className = "field-note";
  intro.textContent =
    "Associez un réseau Wi-Fi (SSID) à un profil de réglages ci-dessus : dès que ce réseau est détecté, " +
    "le profil correspondant est appliqué automatiquement (proxy, chiffrement, notifications, limites de " +
    "débit, restriction DHT/PEX/LSD). Désactivé par défaut.";
  section.appendChild(intro);

  const { row: enabledRow, check: enabledCheck } = paCheckboxRow(
    "anpEnabled",
    "Activer la bascule automatique de profil réseau"
  );
  section.appendChild(enabledRow);
  enabledCheck.addEventListener("change", () => {
    window.bridge.profileAdvanced.setNetworkProfileSwitchEnabled(enabledCheck.checked, () => {});
  });
  window.bridge.profileAdvanced.getNetworkProfileSwitchSettings((values) => {
    enabledCheck.checked = values.enabled;
  });

  const addRow = document.createElement("div");
  addRow.className = "field-row";
  const ssidInput = document.createElement("input");
  ssidInput.type = "text";
  ssidInput.id = "anpSsidInput";
  ssidInput.placeholder = "Nom du réseau Wi-Fi (SSID)";
  addRow.appendChild(ssidInput);

  const profileSelect = document.createElement("select");
  profileSelect.id = "anpProfileSelect";
  addRow.appendChild(profileSelect);

  const addBtn = document.createElement("button");
  addBtn.textContent = "Associer";
  addRow.appendChild(addBtn);
  section.appendChild(addRow);

  const addStatus = document.createElement("p");
  addStatus.className = "status-line";
  addStatus.id = "anpAddStatus";
  section.appendChild(addStatus);

  const list = document.createElement("div");
  list.id = "anpList";
  list.className = "listbox";
  section.appendChild(list);

  addBtn.addEventListener("click", () => {
    const ssid = ssidInput.value.trim();
    const profileName = profileSelect.value;
    window.bridge.profileAdvanced.saveNetworkProfileAssociation(ssid, profileName, (result) => {
      addStatus.textContent = result.error || "";
      if (result.ok) {
        ssidInput.value = "";
        anpReloadAssociations();
      }
    });
  });

  container.appendChild(section);

  // Populated for real once arReloadProfiles() (called from
  // wireProfileAdvanced, after this section is built) resolves -- see
  // arRefreshProfileCombo, which keeps this <select> in sync with the
  // settings-profile list from then on.
}

function wireProfileAdvanced() {
  const container = document.getElementById("profileAdvancedContainer");
  arBuildRulesSection(container);
  arBuildProfilesSection(container);
  anpBuildSection(container);
  arReloadRules();
  arReloadProfiles();
  anpReloadAssociations();
}
